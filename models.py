# models.py
import json
from datetime import datetime
from database import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    avatar_path = db.Column(db.String(500), nullable=True)
    bio = db.Column(db.String(500), default='这个人很神秘，什么都没有留下~')
    role = db.Column(db.Enum('admin', 'user'), default='user', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联的博客和评论
    posts = db.relationship('Post', backref='author_user', lazy=True, foreign_keys='Post.user_id')
    comments = db.relationship('Comment', backref='author_user', lazy=True, foreign_keys='Comment.user_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def avatar_url(self):
        if self.avatar_path:
            return f"/static/{self.avatar_path}" if not self.avatar_path.startswith('uploads/') else f"/{self.avatar_path}"
        return None

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'bio': self.bio,
            'role': self.role,
            'avatar_path': self.avatar_path,
            'created_at': self.created_at.strftime('%Y-%m-%d') if self.created_at else None
        }

    def __repr__(self):
        return f'<User {self.username}>'


class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(50), nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    voice_path = db.Column(db.String(500), nullable=True)       # 语音文件路径
    voice_duration = db.Column(db.Integer, nullable=True)       # 语音时长（秒）

    # 建立与Post模型的关系
    post = db.relationship('Post', backref=db.backref('comments', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Comment {self.id}>'


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    tags = db.Column(db.String(500))
    image_path = db.Column(db.Text)  # 存储JSON字符串
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def image_paths_json(self):
        """返回图片路径的JSON字符串，用于JavaScript"""
        if self.image_path:
            return self.image_path
        return '[]'

    @property
    def image_paths(self):
        """返回图片路径列表"""
        if self.image_path:
            try:
                return json.loads(self.image_path)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @property
    def image_count(self):
        """返回图片数量"""
        return len(self.image_paths)

    @property
    def has_images(self):
        """判断是否有图片"""
        return bool(self.image_paths)

    def __repr__(self):
        return f'<Post {self.title}>'

class Friendship(db.Model):
    """好友关系表"""
    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.Enum('pending', 'accepted', 'rejected'), default='pending', nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    requester = db.relationship('User', foreign_keys=[requester_id], backref='sent_friend_requests')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_friend_requests')

    def __repr__(self):
        return f'<Friendship {self.requester_id}->{self.receiver_id} [{self.status}]>'


class Message(db.Model):
    """私信消息表"""
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=True)           # 文字内容
    image_path = db.Column(db.String(500), nullable=True)  # 图片原图路径
    thumb_path = db.Column(db.String(500), nullable=True)  # 图片缩略图路径
    forwarded_post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)  # 转发的博客ID
    is_deleted_by_sender = db.Column(db.Boolean, default=False)
    is_deleted_by_receiver = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, nullable=False, default=False)
    sender = db.relationship('User', foreign_keys=[sender_id], backref='sent_messages')
    receiver = db.relationship('User', foreign_keys=[receiver_id], backref='received_messages')
    forwarded_post = db.relationship('Post', foreign_keys=[forwarded_post_id], backref='forwarded_messages')

    def __repr__(self):
        return f'<Message {self.sender_id}->{self.receiver_id}>'