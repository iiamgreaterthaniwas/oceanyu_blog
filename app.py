import os
import uuid
import json
import pandas as pd
import io
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from config import Config
from datetime import datetime, timedelta
from database import db, app
from models import Post, Comment
from sqlalchemy import func, extract

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# 添加静态文件服务路由
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/')
def index():
    # 获取查询参数
    search_title = request.args.get('search_title', '').strip()
    search_date = request.args.get('search_date', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 9  # 每页显示12个卡片

    # 构建查询
    query = Post.query

    # 按标题关键词搜索
    if search_title:
        query = query.filter(Post.title.contains(search_title))

    # 按日期搜索
    if search_date:
        try:
            search_date_obj = datetime.strptime(search_date, '%Y-%m-%d').date()

            from sqlalchemy import cast, Date
            query = query.filter(cast(Post.date, Date) == search_date_obj)
        except ValueError:
            flash('日期格式错误，请使用 YYYY-MM-DD 格式', 'error')

    # 添加分页
    posts_pagination = query.order_by(Post.date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    posts = posts_pagination.items

    return render_template('index.html',
                           posts=posts,
                           pagination=posts_pagination,
                           search_title=search_title,
                           search_date=search_date)


@app.route('/add_post', methods=['GET', 'POST'])
def add_post():
    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        tags = request.form.get('tags')

        # 处理多图片上传（移除9张限制）
        image_paths = []
        files = request.files.getlist('images')  # 获取多个文件

        for file in files:
            if file and file.filename and allowed_file(file.filename):
                # 获取文件扩展名
                ext = file.filename.rsplit('.', 1)[1].lower()
                # 生成唯一文件名
                filename = f"{uuid.uuid4().hex}.{ext}"

                os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                image_paths.append(f"uploads/{filename}")

        # 将图片路径列表转换为JSON字符串存储
        image_paths_json = json.dumps(image_paths) if image_paths else None

        # 保存到数据库
        new_post = Post(
            title=request.form['title'],
            content=request.form['content'],
            tags=request.form['tags'],
            image_path=image_paths_json,  # 存储JSON字符串
            date=datetime.utcnow() + timedelta(hours=8)  # 手动设置日期为UTC+8
        )
        db.session.add(new_post)
        db.session.commit()

        flash('文章发布成功！', 'success')
        return redirect(url_for('index'))

    return render_template('add_post.html')


@app.route('/api/posts')
def api_posts():
    page = request.args.get('page', 1, type=int)
    per_page = 9  # 与网页端保持一致

    posts = Post.query.order_by(Post.date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        'success': True,
        'posts': [{
            'id': post.id,
            'title': post.title,
            'content': post.content,
            'tags': post.tags,
            'date': post.date.strftime('%Y-%m-%d'),
            'image_paths_json': post.image_paths_json
        } for post in posts.items],
        'pagination': {
            'page': posts.page,
            'pages': posts.pages,
            'hasPrev': posts.has_prev,
            'hasNext': posts.has_next
        }
    })


@app.route('/edit_post/<int:post_id>', methods=['GET', 'POST'])
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)

    if request.method == 'POST':
        # 更新文章信息
        post.title = request.form.get('title')
        post.content = request.form.get('content')
        post.tags = request.form.get('tags')

        # 处理图片上传
        files = request.files.getlist('images')

        # 获取要保留的旧图片
        keep_images = request.form.getlist('keep_images')

        # 保留的旧图片路径
        kept_image_paths = []
        if post.image_path and keep_images:
            try:
                old_image_paths = json.loads(post.image_path)
                kept_image_paths = [path for i, path in enumerate(old_image_paths) if str(i) in keep_images]
            except (json.JSONDecodeError, Exception):
                kept_image_paths = []

        # 删除不保留的旧图片文件
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

        # 处理新上传的图片
        new_image_paths = []
        if files and files[0].filename:  # 检查是否有新文件上传
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    # 获取文件扩展名
                    ext = file.filename.rsplit('.', 1)[1].lower()
                    # 生成唯一文件名
                    filename = f"{uuid.uuid4().hex}.{ext}"

                    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
                    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(save_path)
                    new_image_paths.append(f"uploads/{filename}")

        # 合并保留的图片和新上传的图片
        all_image_paths = kept_image_paths + new_image_paths
        post.image_path = json.dumps(all_image_paths) if all_image_paths else None

        db.session.commit()
        flash('文章更新成功！', 'success')
        return redirect(url_for('index'))

    # GET请求，显示编辑表单
    # 解析现有图片
    existing_images = []
    if post.image_path:
        try:
            existing_images = json.loads(post.image_path)
        except (json.JSONDecodeError, Exception):
            existing_images = []

    return render_template('edit_post.html', post=post, existing_images=existing_images)


@app.route('/delete_post/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    try:
        post = Post.query.get_or_404(post_id)

        # 删除相关的图片文件
        if post.image_path:
            try:
                image_paths = json.loads(post.image_path)
                for image_path in image_paths:
                    # 构建完整的文件路径
                    full_path = os.path.join(app.root_path, image_path)
                    if os.path.exists(full_path):
                        os.remove(full_path)
            except (json.JSONDecodeError, Exception) as e:
                print(f"删除图片文件时出错: {e}")

        # 从数据库删除文章
        db.session.delete(post)
        db.session.commit()

        return jsonify({'success': True, 'message': '文章删除成功！'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})


@app.route('/get_comments/<int:post_id>')
def get_comments(post_id):
    """获取指定文章的所有评论"""
    comments = Comment.query.filter_by(post_id=post_id).order_by(Comment.date.desc()).all()
    comments_data = []
    for comment in comments:
        comments_data.append({
            'id': comment.id,
            'content': comment.content,
            'author': comment.author,
            'date': comment.date.strftime('%Y-%m-%d %H:%M')
        })
    return jsonify({'comments': comments_data})

@app.route('/add_comment', methods=['POST'])
def add_comment():
    """添加评论"""
    try:
        data = request.get_json()
        post_id = data.get('post_id')
        content = data.get('content', '').strip()
        author = data.get('author', '').strip()

        if not content:
            return jsonify({'success': False, 'message': '评论内容不能为空'})

        if not author:
            return jsonify({'success': False, 'message': '用户名不能为空'})

        if len(author) > 50:
            return jsonify({'success': False, 'message': '用户名不能超过50个字符'})

        # 检查文章是否存在
        post = Post.query.get(post_id)
        if not post:
            return jsonify({'success': False, 'message': '文章不存在'})

        # 创建新评论
        new_comment = Comment(
            post_id=post_id,
            content=content,
            author=author,
            date=datetime.utcnow() + timedelta(hours=8)  # UTC+8
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
                'date': new_comment.date.strftime('%Y-%m-%d %H:%M')
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'添加评论失败: {str(e)}'})


@app.route('/edit_comment/<int:comment_id>', methods=['POST'])
def edit_comment(comment_id):
    """编辑评论"""
    try:
        data = request.get_json()
        content = data.get('content', '').strip()
        author = data.get('author', '').strip()

        if not content:
            return jsonify({'success': False, 'message': '评论内容不能为空'})

        if not author:
            return jsonify({'success': False, 'message': '用户名不能为空'})

        if len(author) > 50:
            return jsonify({'success': False, 'message': '用户名不能超过50个字符'})

        comment = Comment.query.get_or_404(comment_id)
        comment.content = content
        comment.author = author

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
def delete_comment(comment_id):
    """删除评论"""
    try:
        comment = Comment.query.get_or_404(comment_id)
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
