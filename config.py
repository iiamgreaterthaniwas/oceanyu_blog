import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here-change-in-production'
    SQLALCHEMY_DATABASE_URI = 'mysql://root:123456@localhost/oceanyu_blog'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = 'static/uploads'
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    MAX_CONTENT_LENGTH = 500 * 1024 * 1024  # 500MB限制
    # Session 配置
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)  # 登录状态保持30天
