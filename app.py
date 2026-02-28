import os
import uuid
import json
from flask import Flask, render_template, request, redirect, url_for, flash, send_from_directory, jsonify, session, make_response, g
from config import Config
from datetime import datetime, timedelta
from database import db, app
from models import Post, Comment, User, Friendship, Message
from sqlalchemy import cast, Date
from functools import wraps
import time
import requests as http_requests
from PIL import Image, ImageOps
import io

# 确保上传目录存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

COZE_API_TOKEN = "pat_QpFYH4qtFkBBWT6Rbo8qU5ImMEkhgUM6Ot5CeU5VoNFsltAkNzj6193GzOg1FK1U"
COZE_BOT_ID = "7443766574072807458"
COZE_API_BASE = "https://api.coze.cn"
NEW_DOMAINS = ['oceanyublog.top', 'www.oceanyublog.top']  # 新域名列表
OLD_DOMAINS = ['loiioblog.top', 'www.loiioblog.top']  # 旧域名列表


@app.before_request
def check_domain():
    """检查域名，如果是旧域名则显示跳转提示"""
    # 获取当前请求的域名（去掉端口号）
    host = request.host.split(':')[0]

    # 如果是新域名，直接放行
    if host in NEW_DOMAINS:
        return

    # 如果是 localhost 或 127.0.0.1，放行（方便本地调试）
    if host in ['localhost', '127.0.0.1']:
        return

    # 如果是旧域名，显示跳转提示页面
    # 排除静态文件请求（避免样式丢失）
    if host in OLD_DOMAINS and not request.path.startswith('/static/'):
        # 创建一个响应，设置 Cache-Control 为 no-cache，避免浏览器缓存
        response = make_response(render_template('domain_redirect.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response

    # 对于其他未知域名，也显示跳转提示（可选）
    if not request.path.startswith('/static/'):
        response = make_response(render_template('domain_redirect.html'))
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    # 对于静态文件请求，正常处理
    return


# ========== 辅助函数 ==========
def coze_chat(user_message: str, conversation_id: str = None):
    """
    调用 Coze /v3/chat 接口（非流式），轮询直至获得回复。
    返回 (reply_text, conversation_id) 或抛出异常。
    """
    headers = {
        "Authorization": f"Bearer {COZE_API_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "bot_id": COZE_BOT_ID,
        "user_id": "blog_user",  # 可按需改为真实 user_id
        "stream": False,
        "auto_save_history": True,
        "additional_messages": [
            {
                "role": "user",
                "content": user_message,
                "content_type": "text",
            }
        ],
    }

    # 如果传入了 conversation_id，则追加（实现多轮对话）
    if conversation_id:
        payload["conversation_id"] = conversation_id

    # 1. 发起对话
    resp = http_requests.post(
        f"{COZE_API_BASE}/v3/chat",
        headers=headers,
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    result = resp.json()

    chat_data = result.get("data", {})
    chat_id = chat_data.get("id")
    new_conv_id = chat_data.get("conversation_id")

    if not chat_id:
        raise RuntimeError(f"Coze 返回异常: {result}")

    # 2. 轮询状态
    for _ in range(30):
        time.sleep(1)
        retrieve_resp = http_requests.get(
            f"{COZE_API_BASE}/v3/chat/retrieve",
            headers=headers,
            params={"chat_id": chat_id, "conversation_id": new_conv_id},
            timeout=10,
        )
        retrieve_resp.raise_for_status()
        status = retrieve_resp.json().get("data", {}).get("status")

        if status == "completed":
            # 3. 获取消息列表
            msg_resp = http_requests.get(
                f"{COZE_API_BASE}/v3/chat/message/list",
                headers=headers,
                params={"chat_id": chat_id, "conversation_id": new_conv_id},
                timeout=10,
            )
            msg_resp.raise_for_status()
            messages = msg_resp.json().get("data", [])

            # 找到 assistant 的 answer 消息
            for msg in messages:
                if msg.get("role") == "assistant" and msg.get("type") == "answer":
                    return msg.get("content", ""), new_conv_id

            raise RuntimeError("未找到 assistant 回复")

        elif status in ("failed", "requires_action", "canceled"):
            raise RuntimeError(f"对话状态异常: {status}")

    raise TimeoutError("Coze 响应超时（30秒）")


def get_file_full_path(file_path):
    """获取文件的完整系统路径"""
    if not file_path:
        return None

    # 如果路径已经是完整路径（以 / 开头或包含盘符），直接返回
    if os.path.isabs(file_path):
        return file_path

    # 如果路径以 'static/' 开头
    if file_path.startswith('static/'):
        return os.path.join(app.root_path, file_path)

    # 如果路径以 'uploads/' 开头，需要加上 static 目录
    if file_path.startswith('uploads/'):
        return os.path.join(app.root_path, 'static', file_path)

    # 其他情况，默认加上 static/uploads
    return os.path.join(app.root_path, 'static', 'uploads', file_path)


def delete_file(file_path):
    """安全删除文件"""
    if not file_path:
        return False

    full_path = get_file_full_path(file_path)
    try:
        if os.path.exists(full_path):
            os.remove(full_path)
            print(f"文件删除成功: {full_path}")
            return True
        else:
            print(f"文件不存在: {full_path}")
            return False
    except Exception as e:
        print(f"删除文件失败: {full_path}, 错误: {e}")
        return False


def allowed_file(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def save_image_with_thumbnail(file_storage, upload_folder):
    """
    保存原图并生成压缩版缩略图。

    返回:
        orig_path  (str): 原图相对路径，如 'uploads/orig_<uuid>.jpg'
        thumb_path (str): 缩略图相对路径，如 'uploads/thumb_<uuid>.webp'
    """
    uid = uuid.uuid4().hex
    ext = file_storage.filename.rsplit('.', 1)[1].lower() if '.' in file_storage.filename else 'jpg'

    # ---- 原图 ----
    orig_filename = f"orig_{uid}.{ext}"
    orig_save_path = os.path.join(upload_folder, orig_filename)
    file_storage.save(orig_save_path)
    orig_path = f"uploads/{orig_filename}"

    # ---- 压缩图（WebP） ----
    try:
        with Image.open(orig_save_path) as img:
            # 使用 Pillow 的 exif_transpose 方法自动修正方向
            # 这个方法会根据 EXIF 信息自动旋转图片
            img = ImageOps.exif_transpose(img)

            # 如果没有 EXIF 信息，exif_transpose 会返回原图

            # 转换 RGBA/P 为 RGB（WebP 支持 RGBA，但为兼容性统一转 RGB）
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGBA')  # 保留透明通道
            elif img.mode != 'RGB':
                img = img.convert('RGB')

            # 限制最大宽度/高度为 1200px，保持比例
            max_size = (1200, 1200)
            img.thumbnail(max_size, Image.LANCZOS)

            thumb_filename = f"thumb_{uid}.webp"
            thumb_save_path = os.path.join(upload_folder, thumb_filename)
            img.save(thumb_save_path, 'WEBP', quality=82, method=4)
            thumb_path = f"uploads/{thumb_filename}"
    except Exception as e:
        print(f"[图片压缩] 生成缩略图失败，将使用原图: {e}")
        thumb_path = orig_path  # fallback：使用原图

    return orig_path, thumb_path


def get_thumb_path(orig_path):
    """
    根据原图路径推算缩略图路径。
    兼容旧数据（旧路径没有 orig_ 前缀，则直接返回原路径）。
    """
    if not orig_path:
        return orig_path
    basename = os.path.basename(orig_path)
    if basename.startswith('orig_'):
        thumb_basename = 'thumb_' + basename.rsplit('.', 1)[0][5:] + '.webp'
        return os.path.join(os.path.dirname(orig_path), thumb_basename)
    return orig_path  # 旧数据直接返回原路径


def get_current_user():
    """从 session 中获取当前登录用户，同一请求内只查询一次数据库"""
    if '_current_user' not in g:
        user_id = session.get('user_id')
        g._current_user = User.query.get(user_id) if user_id else None
    return g._current_user

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
    """向所有模板注入当前用户和全局未读消息总数"""
    current_user = get_current_user()  # 此时已从 g 缓存读取，不再重复查库
    unread_total = 0
    if current_user:
        unread_total = Message.query.filter(
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.is_deleted_by_receiver == False
        ).count()
    return dict(current_user=current_user, unread_total=unread_total)

# ========== 静态文件路由 ==========

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ========== chat路由 ==========
@app.route('/chat_api', methods=['POST'])
def chat_api():
    """前端聊天组件调用的接口"""
    try:
        data = request.get_json(force=True) or {}
        user_message = data.get('message', '').strip()
        conversation_id = data.get('conversation_id')  # 可选，用于多轮对话

        if not user_message:
            return jsonify({'success': False, 'error': '消息不能为空'})

        reply, new_conv_id = coze_chat(user_message, conversation_id)

        return jsonify({
            'success': True,
            'reply': reply,
            'conversation_id': new_conv_id,
        })

    except TimeoutError as e:
        return jsonify({'success': False, 'error': str(e)}), 504
    except Exception as e:
        app.logger.error(f"chat_api error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


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

        # 创建用户时设置带时区的时间
        new_user = User(
            username=username,
            email=email,
            bio=bio,
            avatar_path=avatar_path,
            role='admin' if is_first_user else 'user',
            created_at=datetime.utcnow() + timedelta(hours=8),  # 添加时区
            updated_at=datetime.utcnow() + timedelta(hours=8)  # 添加时区
        )
        new_user.set_password(password)

        db.session.add(new_user)
        db.session.commit()

        session['user_id'] = new_user.id
        flash(f'注册成功！欢迎加入，{new_user.username}！{"（你是第一个用户，已被设为管理员）" if is_first_user else ""}',
              'success')
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

    # 好友关系状态（仅对登录用户且不是自己时有效）
    friendship_obj = None
    friendship_status = None
    if current_user and current_user.id != user_id:
        friendship_obj, friendship_status = get_friendship_status(current_user.id, user_id)

    return render_template(
        'user_profile.html',
        profile_user=user,
        posts=posts,
        current_user=current_user,
        friendship_status=friendship_status,
        friendship_id=friendship_obj.id if friendship_obj else None,
    )


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
                delete_file(current_user.avatar_path)  # 使用辅助函数删除

            ext = file.filename.rsplit('.', 1)[1].lower()
            filename = f"avatar_{uuid.uuid4().hex}.{ext}"

            # 保存到 static/uploads 目录
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            save_path = os.path.join(upload_folder, filename)
            file.save(save_path)

            current_user.avatar_path = f"uploads/{filename}"

        current_user.bio = bio
        current_user.email = email
        current_user.updated_at = datetime.utcnow() + timedelta(hours=8)  # 更新时区时间

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

        # 确保上传目录存在
        upload_folder = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)

        for file in files:
            if file and file.filename and allowed_file(file.filename):
                orig_path, _thumb_path = save_image_with_thumbnail(file, upload_folder)
                # 只存原图路径；缩略图路径由 get_thumb_path() 实时推算
                image_paths.append(orig_path)

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


@app.route('/get_user_info/<int:user_id>')
def get_user_info(user_id):
    """获取用户信息（头像和管理员状态）"""
    try:
        user = User.query.get_or_404(user_id)
        return jsonify({
            'success': True,
            'avatar_path': user.avatar_path,
            'is_admin': user.role == 'admin',
            'username': user.username
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e)
        })


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

        # 删除不需要的图片文件
        if post.image_path:
            try:
                old_image_paths = json.loads(post.image_path)
                for i, entry in enumerate(old_image_paths):
                    if str(i) not in keep_images:
                        # 兼容旧格式（纯字符串）和新格式（带 orig_ 前缀）
                        orig_path = entry if isinstance(entry, str) else entry.get('orig', '')
                        delete_file(orig_path)
                        # 同时删除对应缩略图
                        thumb_path = get_thumb_path(orig_path)
                        if thumb_path != orig_path:
                            delete_file(thumb_path)
            except (json.JSONDecodeError, Exception) as e:
                print(f"删除旧图片文件时出错: {e}")

        # 上传新图片
        new_image_paths = []
        if files and files[0].filename:
            upload_folder = os.path.join(app.root_path, 'static', 'uploads')
            os.makedirs(upload_folder, exist_ok=True)
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    orig_path, _thumb_path = save_image_with_thumbnail(file, upload_folder)
                    new_image_paths.append(orig_path)

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

        # 删除博客关联的图片文件（原图 + 缩略图）
        if post.image_path:
            try:
                image_paths = json.loads(post.image_path)
                for entry in image_paths:
                    orig_path = entry if isinstance(entry, str) else entry.get('orig', '')
                    delete_file(orig_path)
                    thumb_path = get_thumb_path(orig_path)
                    if thumb_path != orig_path:
                        delete_file(thumb_path)
            except (json.JSONDecodeError, Exception) as e:
                print(f"删除图片文件时出错: {e}")

        # 删除博客关联的评论中的语音文件
        comments = Comment.query.filter_by(post_id=post_id).all()
        for comment in comments:
            if comment.voice_path:
                delete_file(comment.voice_path)  # 使用辅助函数删除
            db.session.delete(comment)

        db.session.delete(post)
        db.session.commit()

        return jsonify({'success': True, 'message': '文章及关联文件删除成功！'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除失败: {str(e)}'})


@app.route('/upload_voice', methods=['POST'])
@login_required
def upload_voice():
    """上传语音文件，返回文件路径和时长"""
    try:
        file = request.files.get('voice')
        duration = request.form.get('duration', 0, type=int)
        if not file or not file.filename:
            return jsonify({'success': False, 'message': '未上传文件'})

        ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'wav'
        filename = f"voice_{uuid.uuid4().hex}.{ext}"

        # 保存到 static/uploads 目录
        upload_folder = os.path.join(app.root_path, 'static', 'uploads')
        os.makedirs(upload_folder, exist_ok=True)
        save_path = os.path.join(upload_folder, filename)
        file.save(save_path)

        voice_path = f"uploads/{filename}"
        return jsonify({'success': True, 'voice_path': voice_path, 'duration': duration})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


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
        is_admin = False  # 默认不是管理员

        if comment.author_user:
            author_avatar = comment.author_user.avatar_path
            author_id = comment.author_user.id
            is_admin = comment.author_user.role == 'admin'  # 判断是否为管理员

        comments_data.append({
            'id': comment.id,
            'content': comment.content,
            'author': comment.author,
            'date': comment.date.strftime('%Y-%m-%d %H:%M'),
            'can_edit': can_edit,
            'author_avatar': author_avatar,
            'author_id': author_id,
            'is_admin': is_admin,
            'voice_path': comment.voice_path,
            'voice_duration': comment.voice_duration
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

        voice_path = data.get('voice_path')
        voice_duration = data.get('voice_duration')

        new_comment = Comment(
            post_id=post_id,
            content=content,
            author=current_user.username,
            user_id=current_user.id,
            date=datetime.utcnow() + timedelta(hours=8),
            voice_path=voice_path,
            voice_duration=voice_duration
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
                'author_id': current_user.id,
                'is_admin': current_user.role == 'admin',
                'voice_path': new_comment.voice_path,
                'voice_duration': new_comment.voice_duration
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

        # 获取评论作者信息
        is_admin = comment.author_user.role == 'admin' if comment.author_user else False

        return jsonify({
            'success': True,
            'message': '评论更新成功',
            'comment': {
                'id': comment.id,
                'content': comment.content,
                'author': comment.author,
                'date': comment.date.strftime('%Y-%m-%d %H:%M'),
                'author_id': comment.user_id,
                'author_avatar': comment.author_user.avatar_path if comment.author_user else None,
                'is_admin': is_admin  # 添加管理员标志
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

        # 删除评论关联的语音文件
        if comment.voice_path:
            delete_file(comment.voice_path)  # 使用辅助函数删除

        db.session.delete(comment)
        db.session.commit()

        return jsonify({'success': True, 'message': '评论及语音文件删除成功'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'删除评论失败: {str(e)}'})


# ========== 图片下载路由（强制下载原图）==========

@app.route('/download_image/<path:image_path>')
def download_image(image_path):
    """
    强制下载原图。
    URL 示例: /download_image/uploads/orig_abc123.jpg
    """
    # 安全校验：只允许 uploads/ 目录下的文件
    if not image_path.startswith('uploads/'):
        return '非法路径', 403

    full_path = os.path.join(app.root_path, 'static', image_path)
    if not os.path.exists(full_path):
        return '文件不存在', 404

    directory = os.path.dirname(full_path)
    filename = os.path.basename(full_path)
    return send_from_directory(directory, filename, as_attachment=True)


# ========== Jinja2 模板过滤器 ==========

@app.template_filter('thumb_path')
def thumb_path_filter(orig_path):
    """模板中使用: {{ image_path | thumb_path }}，返回缩略图路径"""
    return get_thumb_path(orig_path)


# ========== 好友功能辅助 ==========

def get_friends(user_id):
    """获取已接受的好友列表"""
    friendships = Friendship.query.filter(
        ((Friendship.requester_id == user_id) | (Friendship.receiver_id == user_id)),
        Friendship.status == 'accepted'
    ).all()
    friends = []
    for f in friendships:
        friend = f.receiver if f.requester_id == user_id else f.requester
        friends.append(friend)
    return friends


def are_friends(user_id_a, user_id_b):
    """检查两用户是否是好友"""
    return Friendship.query.filter(
        ((Friendship.requester_id == user_id_a) & (Friendship.receiver_id == user_id_b)) |
        ((Friendship.requester_id == user_id_b) & (Friendship.receiver_id == user_id_a)),
        Friendship.status == 'accepted'
    ).first() is not None


def get_friendship_status(current_user_id, other_user_id):
    """获取两用户之间的好友关系状态"""
    f = Friendship.query.filter(
        ((Friendship.requester_id == current_user_id) & (Friendship.receiver_id == other_user_id)) |
        ((Friendship.requester_id == other_user_id) & (Friendship.receiver_id == current_user_id))
    ).first()
    if not f:
        return None, None
    return f, f.status


# ========== 好友博客页 ==========

@app.route('/friend_posts')
@login_required
def friend_posts():
    current_user = get_current_user()
    friends = get_friends(current_user.id)
    friend_ids = [f.id for f in friends]
    page = request.args.get('page', 1, type=int)
    per_page = 9
    if friend_ids:
        posts_pagination = Post.query.filter(Post.user_id.in_(friend_ids)).order_by(Post.date.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    else:
        posts_pagination = Post.query.filter(Post.id == -1).paginate(page=1, per_page=per_page, error_out=False)
    return render_template('friend_posts.html',
                           posts=posts_pagination.items,
                           pagination=posts_pagination,
                           friends=friends,
                           friends_json=[{  # ← 新增这个
                               'id': f.id,
                               'username': f.username,
                               'avatar_path': f.avatar_path or None
                           } for f in friends],
                           current_user=current_user,
                           get_thumb_path=get_thumb_path)


# ========== 消息列表页 ==========

@app.route('/messages')
@login_required
def messages_list():
    current_user = get_current_user()
    friends = get_friends(current_user.id)
    conversations = []
    for friend in friends:
        last_msg = Message.query.filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == friend.id) & (
                        Message.is_deleted_by_sender == False)) |
            ((Message.sender_id == friend.id) & (Message.receiver_id == current_user.id) & (
                        Message.is_deleted_by_receiver == False))
        ).order_by(Message.created_at.desc()).first()

        # 只统计真正未读的消息
        unread_count = Message.query.filter(
            Message.sender_id == friend.id,
            Message.receiver_id == current_user.id,
            Message.is_read == False,
            Message.is_deleted_by_receiver == False
        ).count()

        conversations.append({
            'friend': friend,
            'last_msg': last_msg,
            'unread_count': unread_count
        })
    conversations.sort(
        key=lambda x: x['last_msg'].created_at if x['last_msg'] else datetime.min,
        reverse=True
    )
    return render_template('messages.html', conversations=conversations, current_user=current_user)


# ========== 具体聊天页 ==========

@app.route('/chat/<int:friend_id>')
@login_required
def chat(friend_id):
    current_user = get_current_user()
    friend = User.query.get_or_404(friend_id)
    if not are_friends(current_user.id, friend_id):
        flash('你们还不是好友', 'error')
        return redirect(url_for('messages_list'))

    # 将该好友发给我的所有未读消息标记为已读
    Message.query.filter(
        Message.sender_id == friend_id,
        Message.receiver_id == current_user.id,
        Message.is_read == False
    ).update({'is_read': True})
    db.session.commit()

    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id) & (
                    Message.is_deleted_by_sender == False)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id) & (
                    Message.is_deleted_by_receiver == False))
    ).order_by(Message.created_at.asc()).all()

    return render_template('chat.html', friend=friend, messages=messages, current_user=current_user)


@app.route('/mark_read/<int:friend_id>', methods=['POST'])
@login_required
def mark_read(friend_id):
    """将指定好友发来的未读消息全部标记为已读"""
    current_user = get_current_user()
    updated = Message.query.filter(
        Message.sender_id == friend_id,
        Message.receiver_id == current_user.id,
        Message.is_read == False
    ).update({'is_read': True})
    db.session.commit()

    # 返回新的全局未读总数，供前端更新底部栏角标
    new_total = Message.query.filter(
        Message.receiver_id == current_user.id,
        Message.is_read == False,
        Message.is_deleted_by_receiver == False
    ).count()

    return jsonify({'success': True, 'updated': updated, 'unread_total': new_total})


# ========== 发送消息 API ==========

@app.route('/send_message', methods=['POST'])
@login_required
def send_message():
    current_user = get_current_user()
    receiver_id = request.form.get('receiver_id', type=int)
    content = request.form.get('content', '').strip()
    forwarded_post_id = request.form.get('forwarded_post_id', type=int)

    if not receiver_id:
        return jsonify({'success': False, 'error': '接收者不存在'})
    if not are_friends(current_user.id, receiver_id):
        return jsonify({'success': False, 'error': '你们还不是好友'})

    image_path = None
    thumb_path = None
    file = request.files.get('image')
    if file and file.filename and allowed_file(file.filename):
        orig_path, t_path = save_image_with_thumbnail(file, app.config['UPLOAD_FOLDER'])
        image_path = orig_path
        thumb_path = t_path

    if not content and not image_path and not forwarded_post_id:
        return jsonify({'success': False, 'error': '消息不能为空'})

    msg = Message(
        sender_id=current_user.id,
        receiver_id=receiver_id,
        content=content or None,
        image_path=image_path,
        thumb_path=thumb_path,
        forwarded_post_id=forwarded_post_id or None,
        created_at=datetime.utcnow() + timedelta(hours=8)
    )
    db.session.add(msg)
    db.session.commit()

    # 构建返回数据
    msg_data = {
        'id': msg.id,
        'sender_id': msg.sender_id,
        'content': msg.content,
        'image_thumb': f'/static/{msg.thumb_path}' if msg.thumb_path else None,
        'image_orig': f'/static/{msg.image_path}' if msg.image_path else None,
        'forwarded_post': None,
        'created_at': msg.created_at.strftime('%H:%M'),
        'created_at_full': msg.created_at.strftime('%Y-%m-%d %H:%M'),
    }
    if msg.forwarded_post_id and msg.forwarded_post:
        post = msg.forwarded_post
        msg_data['forwarded_post'] = {
            'id': post.id,
            'title': post.title,
            'content': post.content[:100],
        }
    return jsonify({'success': True, 'message': msg_data})


# ========== 删除消息 API ==========

@app.route('/delete_message/<int:msg_id>', methods=['POST'])
@login_required
def delete_message(msg_id):
    current_user = get_current_user()
    msg = Message.query.get_or_404(msg_id)
    if msg.sender_id == current_user.id:
        msg.is_deleted_by_sender = True
    elif msg.receiver_id == current_user.id:
        msg.is_deleted_by_receiver = True
    else:
        return jsonify({'success': False, 'error': '无权限'})
    db.session.commit()
    return jsonify({'success': True})


# ========== 联系人页 / 好友管理 ==========

@app.route('/contacts')
@login_required
def contacts():
    current_user = get_current_user()
    friends = get_friends(current_user.id)
    pending_received = Friendship.query.filter_by(receiver_id=current_user.id, status='pending').all()
    pending_sent = Friendship.query.filter_by(requester_id=current_user.id, status='pending').all()
    return render_template('contacts.html',
                           friends=friends,
                           pending_received=pending_received,
                           pending_sent=pending_sent,
                           current_user=current_user)


# ========== 添加好友 ==========

@app.route('/add_friend/<int:user_id>', methods=['POST'])
@login_required
def add_friend(user_id):
    current_user = get_current_user()
    if user_id == current_user.id:
        return jsonify({'success': False, 'error': '不能添加自己为好友'})
    target = User.query.get_or_404(user_id)
    existing, status = get_friendship_status(current_user.id, user_id)
    if existing:
        if status == 'accepted':
            return jsonify({'success': False, 'error': '你们已经是好友了'})
        elif status == 'pending':
            return jsonify({'success': False, 'error': '请求已发送，等待对方同意'})
    f = Friendship(requester_id=current_user.id, receiver_id=user_id)
    db.session.add(f)
    db.session.commit()
    return jsonify({'success': True, 'message': f'好友请求已发送给 {target.username}'})


# ========== 接受好友请求 ==========

@app.route('/accept_friend/<int:friendship_id>', methods=['POST'])
@login_required
def accept_friend(friendship_id):
    current_user = get_current_user()
    f = Friendship.query.get_or_404(friendship_id)
    if f.receiver_id != current_user.id:
        return jsonify({'success': False, 'error': '无权限'})
    f.status = 'accepted'
    db.session.commit()
    return jsonify({'success': True, 'message': f'已接受 {f.requester.username} 的好友请求'})


# ========== 拒绝好友请求 ==========

@app.route('/reject_friend/<int:friendship_id>', methods=['POST'])
@login_required
def reject_friend(friendship_id):
    current_user = get_current_user()
    f = Friendship.query.get_or_404(friendship_id)
    if f.receiver_id != current_user.id:
        return jsonify({'success': False, 'error': '无权限'})
    db.session.delete(f)
    db.session.commit()
    return jsonify({'success': True})


# ========== 删除好友 ==========

@app.route('/remove_friend/<int:user_id>', methods=['POST'])
@login_required
def remove_friend(user_id):
    current_user = get_current_user()
    f = Friendship.query.filter(
        ((Friendship.requester_id == current_user.id) & (Friendship.receiver_id == user_id)) |
        ((Friendship.requester_id == user_id) & (Friendship.receiver_id == current_user.id)),
        Friendship.status == 'accepted'
    ).first()
    if not f:
        return jsonify({'success': False, 'error': '好友关系不存在'})
    db.session.delete(f)
    db.session.commit()
    return jsonify({'success': True})


# ========== 搜索用户（添加好友用） ==========

@app.route('/search_users')
@login_required
def search_users():
    current_user = get_current_user()
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'users': []})
    users = User.query.filter(
        User.username.contains(q),
        User.id != current_user.id
    ).limit(10).all()
    result = []
    for u in users:
        _, status = get_friendship_status(current_user.id, u.id)
        result.append({
            'id': u.id,
            'username': u.username,
            'bio': u.bio,
            'avatar': f'/static/{u.avatar_path}' if u.avatar_path else None,
            'friendship_status': status
        })
    return jsonify({'users': result})


# ========== 转发博客给好友 ==========

@app.route('/forward_post/<int:post_id>', methods=['POST'])
@login_required
def forward_post(post_id):
    current_user = get_current_user()
    post = Post.query.get_or_404(post_id)
    receiver_ids = request.json.get('receiver_ids', [])
    if not receiver_ids:
        return jsonify({'success': False, 'error': '请选择要转发的好友'})
    sent_to = []
    for rid in receiver_ids:
        if not are_friends(current_user.id, rid):
            continue
        msg = Message(
            sender_id=current_user.id,
            receiver_id=rid,
            forwarded_post_id=post_id,
            created_at=datetime.utcnow() + timedelta(hours=8)
        )
        db.session.add(msg)
        sent_to.append(rid)
    db.session.commit()
    return jsonify({'success': True, 'sent_to': sent_to, 'count': len(sent_to)})


# ========== 获取聊天消息（轮询 API） ==========

@app.route('/poll_messages/<int:friend_id>')
@login_required
def poll_messages(friend_id):
    current_user = get_current_user()
    after_id = request.args.get('after_id', 0, type=int)
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == friend_id) & (
                    Message.is_deleted_by_sender == False)) |
        ((Message.sender_id == friend_id) & (Message.receiver_id == current_user.id) & (
                    Message.is_deleted_by_receiver == False)),
        Message.id > after_id
    ).order_by(Message.created_at.asc()).all()

    result = []
    for msg in messages:
        item = {
            'id': msg.id,
            'sender_id': msg.sender_id,
            'content': msg.content,
            'image_thumb': f'/static/{msg.thumb_path}' if msg.thumb_path else None,
            'image_orig': f'/static/{msg.image_path}' if msg.image_path else None,
            'forwarded_post': None,
            'created_at': msg.created_at.strftime('%H:%M'),
            'created_at_full': msg.created_at.strftime('%Y-%m-%d %H:%M'),
        }
        if msg.forwarded_post_id and msg.forwarded_post:
            p = msg.forwarded_post
            imgs = p.image_paths
            item['forwarded_post'] = {
                'id': p.id,
                'title': p.title,
                'content': p.content[:100],
                'thumb': f'/static/{get_thumb_path(imgs[0])}' if imgs else None
            }
        result.append(item)
    return jsonify({'messages': result})


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)