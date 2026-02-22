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
