from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Prediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, default=None)
    customer_id = db.Column(db.String(64), nullable=True)
    name = db.Column(db.String(120), nullable=True)
    features = db.Column(db.Text, nullable=False)
    predicted_label = db.Column(db.String(32), nullable=False)
    probability = db.Column(db.Float, nullable=False)
    risk_score = db.Column(db.Integer, nullable=False)
    risk_category = db.Column(db.String(32), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ApprovalPrediction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, default=None)
    customer_id = db.Column(db.String(64), nullable=True)
    name = db.Column(db.String(120), nullable=True)
    features = db.Column(db.Text, nullable=False)
    predicted_label = db.Column(db.String(32), nullable=False)  # Approve/Reject
    probability = db.Column(db.Float, nullable=False)  # Approval probability
    approval_score = db.Column(db.Integer, nullable=False)  # 0-100
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
