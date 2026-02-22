# models.py
import json
from datetime import datetime
from database import db

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author = db.Column(db.String(50), nullable=False) 
    date = db.Column(db.DateTime, default=datetime.utcnow)

    # 建立与Post模型的关系
    post = db.relationship('Post', backref=db.backref('comments', lazy=True, cascade='all, delete-orphan'))

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    tags = db.Column(db.String(500))
    image_path = db.Column(db.Text)  # 存储JSON字符串

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
        
