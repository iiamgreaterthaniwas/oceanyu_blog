import os
import uuid
import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, session
from config import Config
from datetime import datetime, timedelta
from database import db, app
from models import Post, Comment, User
from sqlalchemy import cast, Date
from functools import wraps

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ========== 辅助函数 ==========

def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_current_user():
    """从 session 中获取当前登录用户"""
    user_id = session.get('user_id')
    if user_id:
        return User.query.get(user_id)
    return None


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('user_id'):
            flash('请先登录', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def can_edit_post(post, current_user):
    """判断当前用户是否可以编辑/删除该博客"""
    if not current_user:
        return False
    if current_user.is_admin:
        return True
    return post.user_id == current_user.id


def can_edit_comment(comment, current_user):
    """判断当前用户是否可以编辑/删除该评论"""
    if not current_user:
        return False
    if current_user.is_admin:
        return True
    return comment.user_id == current_user.id


@app.context_processor
def inject_user():
    """向所有模板注入当前用户"""
    return dict(current_user=get_current_user())


# ========== 静态文件路由 ==========

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ========== 主页 ==========

@app.route('/')
def index():
    search_title = request.args.get('search_title', '').strip()
    search_date = request.args.get('search_date', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 9

    query = Post.query

    if search_title:
        query = query.filter(Post.title.contains(search_title))

    if search_date:
        try:
            search_date_obj = datetime.strptime(search_date, '%Y-%m-%d').date()
            query = query.filter(cast(Post.date, Date) == search_date_obj)
        except ValueError:
            flash('日期格式错误，请使用 YYYY-MM-DD 格式', 'error')

    posts_pagination = query.order_by(Post.date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    posts = posts_pagination.items
    current_user = get_current_user()

    return render_template('index.html',
                           posts=posts,
                           pagination=posts_pagination,
                           search_title=search_title,
                           search_date=search_date,
                           current_user=current_user)


# ========== 用户认证 ==========

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('user_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('用户名和密码不能为空', 'error')
            return render_template('login.html')

        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            session['user_id'] = user.id
            session.permanent = True
            flash(f'欢迎回来，{user.username}！', 'success')
            return redirect(url_for('index'))
        else:
            flash('用户名或密码错误', 'error')

    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if session.get('user_id'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        email = request.form.get('email', '').strip() or None
        bio = request.form.get('bio', '').strip() or '这个人很神秘，什么都没有留下~'

        # 验证
        if not username or not password:
            flash('用户名和密码不能为空', 'error')
            return render_template('register.html')

        if len(username) < 2 or len(username) > 20:
            flash('用户名长度须在2-20个字符之间', 'error')
            return render_template('register.html')

        if len(password) < 6:
            flash('密码不能少于6位', 'error')
            return render_template('register.html')

        if password != confirm_password:
            flash('两次输入的密码不一致', 'error')
            return render_template('register.html')

        if User.query.filter_by(username=username).first():
            flash('该用户名已被注册', 'error')
            return render_template('register.html')

        if email and User.query.filter_by(email=email).first():
            flash('该邮箱已被注册', 'error')
            return render_template('register.html')

        # 处理头像上传
        avatar_path = None
        file = request.files.get('avatar')
        if file and file.filename and allowed_file(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"avatar_{uuid.uuid4().hex}.{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(save_path)
            avatar_path = f"uploads/{filename}"

        # 判断是否为第一个用户（自动设为管理员）
        is_first_user = User.query.count() == 0

        new_user = User(
            username=username,
            email=email,
            bio=bio,
            avatar_path=avatar_path,
            role='admin' if is_first_user else 'user'
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        session['user_id'] = new_user.id
        flash(f'注册成功！欢迎加入，{new_user.username}！{"（你是第一个用户，已被设为管理员）" if is_first_user else ""}', 'success')
        return redirect(url_for('index'))

    return render_template('register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('已退出登录', 'success')
    return redirect(url_for('index'))


# ========== 用户详情页 ==========

@app.route('/user/<int:user_id>')
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    current_user = get_current_user()
    # 获取该用户的博客
    posts = Post.query.filter_by(user_id=user_id).order_by(Post.date.desc()).all()
    return render_template('user_profile.html', profile_user=user, posts=posts, current_user=current_user)


@app.route('/user/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    current_user = get_current_user()

    if request.method == 'POST':
        bio = request.form.get('bio', '').strip() or '这个人很神秘，什么都没有留下~'
        email = request.form.get('email', '').strip() or None
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')

        # 验证邮箱唯一性
        if email and email != current_user.email:
            existing = User.query.filter_by(email=email).first()
            if existing and existing.id != current_user.id:
                flash('该邮箱已被使用', 'error')
                return render_template('edit_profile.html', current_user=current_user)

        # 处理密码修改
        if new_password:
            if len(new_password) < 6:
                flash('新密码不能少于6位', 'error')
                return render_template('edit_profile.html', current_user=current_user)
            if new_password != confirm_password:
                flash('两次输入的密码不一致', 'error')
                return render_template('edit_profile.html', current_user=current_user)
            current_user.set_password(new_password)

        # 处理头像上传
        file = request.files.get('avatar')
        if file and file.filename and allowed_file(file.filename):
            # 删除旧头像
            if current_user.avatar_path:
                old_path = os.path.join(app.root_path, current_user.avatar_path)
                if os.path.exists(old_path):
                    os.remove(old_path)

            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"avatar_{uuid.uuid4().hex}.{ext}"
            save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(save_path)
            current_user.avatar_path = f"uploads/{filename}"

        current_user.bio = bio
        current_user.email = email
        db.session.commit()

        flash('个人信息更新成功！', 'success')
        return redirect(url_for('user_profile', user_id=current_user.id))

    return render_template('edit_profile.html', current_user=current_user)


# ========== 博客操作 ==========

@app.route('/add_post', methods=['GET', 'POST'])
@login_required
def add_post():
    current_user = get_current_user()

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        tags = request.form.get('tags')

        image_paths = []
        files = request.files.getlist('images')

        for file in files:
            if file and file.filename and allowed_file(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{uuid.uuid4().hex}.{ext}"
                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                image_paths.append(f"uploads/{filename}")

        image_paths_json = json.dumps(image_paths) if image_paths else None

        new_post = Post(
            title=title,
            content=content,
            tags=tags,
            image_path=image_paths_json,
            date=datetime.utcnow() + timedelta(hours=8),
            user_id=current_user.id
        )
        db.session.add(new_post)
        db.session.commit()

        flash('文章发布成功！', 'success')
        return redirect(url_for('index'))

    return render_template('add_post.html', current_user=current_user)


@app.route('/api/posts')
def api_posts():
    page = request.args.get('page', 1, type=int)
    per_page = 9

    posts = Post.query.order_by(Post.date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    current_user = get_current_user()

    return jsonify({
        'success': True,
        'posts': [{
            'id': post.id,
            'title': post.title,
            'content': post.content,
            'tags': post.tags,
            'date': post.date.strftime('%Y-%m-%d'),
            'image_paths_json': post.image_paths_json,
            'author': post.author_user.username if post.author_user else post.tags,
            'can_edit': can_edit_post(post, current_user)
        } for post in posts.items],
        'pagination': {
            'page': posts.page,
            'pages': posts.pages,
            'hasPrev': posts.has_prev,
            'hasNext': posts.has_next
        }
    })


@app.route('/edit_post/<int:post_id>', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    current_user = get_current_user()

    if not can_edit_post(post, current_user):
        flash('你没有权限编辑这篇文章', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        post.tags = request.form.get('tags')

        files = request.files.getlist('images')
        keep_images = request.form.getlist('keep_images')

        kept_image_paths = []
        if post.image_path and keep_images:
            try:
                old_image_paths = json.loads(post.image_path)
                kept_image_paths = [path for i, path in enumerate(old_image_paths) if str(i) in keep_images]
            except (json.JSONDecodeError, Exception):
                kept_image_paths = []

        if post.image_path:
            try:
                old_image_paths = json.loads(post.image_path)
                for i, image_path in enumerate(old_image_paths):
                    if str(i) not in keep_images:
                        full_path = os.path.join(app.root_path, image_path)
                        if os.path.exists(full_path):
                            os.remove(full_path)
            except (json.JSONDecodeError, Exception) as e:
                print(f"删除旧图片文件时出错: {e}")

        new_image_paths = []
        if files and files[0].filename:
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    filename = f"{uuid.uuid4().hex}.{ext}"
                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(save_path)
                    new_image_paths.append(f"uploads/{filename}")

        all_image_paths = kept_image_paths + new_image_paths
        post.image_path = json.dumps(all_image_paths) if all_image_paths else None

        db.session.commit()
        flash('文章更新成功！', 'success')
        return redirect(url_for('index'))

    existing_images = []
    if post.image_path:
        try:
            existing_images = json.loads(post.image_path)
        except (json.JSONDecodeError, Exception):
            existing_images = []

    return render_template('edit_post.html', post=post, existing_images=existing_images, current_user=current_user)


@app.route('/delete_post/<int:post_id>', methods=['POST'])
@login_required
def delete_post(post_id):
    try:
        post = Post.query.get_or_404(post_id)
        current_user = get_current_user()

        if not can_edit_post(post, current_user):
            return jsonify({'success': False, 'message': '你没有权限删除这篇文章'})

        if post.image_path:
            try:
                image_paths = json.loads(post.image_path)
                for image_path in image_paths:
                    full_path = os.path.join(app.root_path, image_path)
                    if os.path.exists(full_path):
                        os.remove(full_path)
            except (json.JSONDecodeError, Exception) as e:
                print(f"删除图片文件时出错: {e}")

        db.session.delete(post)
        db.session.commit()

        return jsonify({'success': True, 'message': '文章删除成功！'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})


# ========== 评论操作 ==========

@app.route('/get_comments/<int:post_id>')
def get_comments(post_id):
    current_user = get_current_user()
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.date.desc()).all()
    comments_data = []
    for comment in comments:
        can_edit = can_edit_comment(comment, current_user)
        author_avatar = None
        author_id = None
        if comment.author_user:
            author_avatar = comment.author_user.avatar_path
            author_id = comment.author_user.id
        comments_data.append({
            'id': comment.id,
            'content': comment.content,
            'author': comment.author,
            'date': comment.date.strftime('%Y-%m-%d %H:%M'),
            'can_edit': can_edit,
            'author_avatar': author_avatar,
            'author_id': author_id
        })
    return jsonify({'comments': comments_data})


@app.route('/add_comment', methods=['POST'])
@login_required
def add_comment():
    try:
        current_user = get_current_user()
        data = request.get_json()
        post_id = data.get('post_id')
        content = data.get('content', '').strip()

        if not content:
            return jsonify({'success': False, 'message': '评论内容不能为空'})

        post = Post.query.get(post_id)
        if not post:
            return jsonify({'success': False, 'message': '文章不存在'})

        new_comment = Comment(
            post_id=post_id,
            content=content,
            author=current_user.username,
            user_id=current_user.id,
            date=datetime.utcnow() + timedelta(hours=8)
        )

        db.session.add(new_comment)
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '评论添加成功',
            'comment': {
                'id': new_comment.id,
                'content': new_comment.content,
                'author': new_comment.author,
                'date': new_comment.date.strftime('%Y-%m-%d %H:%M'),
                'can_edit': True,
                'author_avatar': current_user.avatar_path,
                'author_id': current_user.id
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'添加评论失败: {str(e)}'})


@app.route('/edit_comment/<int:comment_id>', methods=['POST'])
@login_required
def edit_comment(comment_id):
    try:
        current_user = get_current_user()
        comment = Comment.query.get_or_404(comment_id)

        if not can_edit_comment(comment, current_user):
            return jsonify({'success': False, 'message': '你没有权限编辑这条评论'})

        data = request.get_json()
        content = data.get('content', '').strip()

        if not content:
            return jsonify({'success': False, 'message': '评论内容不能为空'})

        comment.content = content
        db.session.commit()

        return jsonify({
            'success': True,
            'message': '评论更新成功',
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'author': comment.author,
                'date': comment.date.strftime('%Y-%m-%d %H:%M')
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'更新评论失败: {str(e)}'})


@app.route('/delete_comment/<int:comment_id>', methods=['POST'])
@login_required
def delete_comment(comment_id):
    try:
        current_user = get_current_user()
        comment = Comment.query.get_or_404(comment_id)

        if not can_edit_comment(comment, current_user):
            return jsonify({'success': False, 'message': '你没有权限删除这条评论'})

        db.session.delete(comment)
        db.session.commit()

        return jsonify({'success': True, 'message': '评论删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除评论失败: {str(e)}'})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
