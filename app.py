import os
import json
import tempfile
import warnings
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from flask_cors import CORS
from dotenv import load_dotenv
from models import db, User, Prediction, ApprovalPrediction
from train_model import (
    create_default_feature_frame,
    compute_default_probability,
    compute_default_risk_category,
    generate_and_train_approval_model,
    generate_and_train_default_model,
)
import joblib
from sklearn.exceptions import InconsistentVersionWarning
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib import colors
from sqlalchemy import func
import pymysql

load_dotenv()

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def resolve_project_path(environment_name, default_relative_path):
    configured_path = os.getenv(environment_name, default_relative_path)
    if os.path.isabs(configured_path):
        return configured_path
    return os.path.join(PROJECT_ROOT, configured_path)


def sqlite_url(database_path):
    return f"sqlite:///{database_path.replace(os.sep, '/')}"


def normalize_approval_label(label):
    if label is None:
        return 'Rejected'
    normalized = str(label).strip().lower()
    if normalized in {'approve', 'approved', 'approved loan', 'loan approved'}:
        return 'Approved'
    if normalized in {'reject', 'rejected', 'rejected loan', 'loan rejected'}:
        return 'Rejected'
    return 'Approved' if normalized in {'approved'} else 'Rejected' if normalized in {'rejected'} else str(label).strip() or 'Rejected'


def normalize_risk_bucket(category):
    normalized = str(category or '').strip().lower()
    if normalized in {'very low', 'low'}:
        return 'Low'
    if normalized in {'moderate', 'medium'}:
        return 'Medium'
    if normalized in {'high', 'very high', 'critical'}:
        return 'High'
    return 'Medium'


def cleanup_prediction_history():
    default_items = Prediction.query.order_by(Prediction.id.asc()).all()
    seen_default_keys = set()
    for item in default_items:
        if item.created_at is None or not str(item.predicted_label or '').strip():
            db.session.delete(item)
            continue
        item.predicted_label = str(item.predicted_label).strip()
        item.risk_category = normalize_risk_bucket(item.risk_category)
        key = (
            item.user_id,
            str(item.customer_id or ''),
            str(item.name or ''),
            item.predicted_label,
            item.probability,
            item.risk_score,
            item.risk_category,
            str(item.features or ''),
            item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
        )
        if key in seen_default_keys:
            db.session.delete(item)
        else:
            seen_default_keys.add(key)

    approval_items = ApprovalPrediction.query.order_by(ApprovalPrediction.id.asc()).all()
    seen_approval_keys = set()
    for item in approval_items:
        if item.created_at is None or not str(item.predicted_label or '').strip():
            db.session.delete(item)
            continue
        item.predicted_label = normalize_approval_label(item.predicted_label)
        key = (
            item.user_id,
            str(item.customer_id or ''),
            str(item.name or ''),
            item.predicted_label,
            item.probability,
            item.approval_score,
            str(item.features or ''),
            item.created_at.strftime('%Y-%m-%d %H:%M:%S') if item.created_at else None,
        )
        if key in seen_approval_keys:
            db.session.delete(item)
        else:
            seen_approval_keys.add(key)

    db.session.commit()


def _apply_history_date_filters(query, model_class, from_date_str=None, to_date_str=None):
    if from_date_str:
        from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
        query = query.filter(model_class.created_at >= from_date)
    if to_date_str:
        to_date = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1) - timedelta(seconds=1)
        query = query.filter(model_class.created_at <= to_date)
    return query


def _get_scoped_history_query(model_class, is_admin, user_id, from_date_str=None, to_date_str=None):
    query = model_class.query
    if not is_admin:
        query = query.filter_by(user_id=user_id)
    return _apply_history_date_filters(query, model_class, from_date_str, to_date_str)


def _build_combined_history(default_items, approval_items):
    combined = []

    for p in default_items:
        if p.created_at is None or not str(p.predicted_label or '').strip():
            continue
        combined.append({
            'type': 'default',
            'id': p.id,
            'customer_id': p.customer_id,
            'name': p.name,
            'label': p.predicted_label,
            'predicted_label': p.predicted_label,
            'probability': p.probability,
            'risk_score': p.risk_score,
            'risk_category': normalize_risk_bucket(p.risk_category),
            'approval_score': None,
            '_sort_at': p.created_at,
        })

    for p in approval_items:
        if p.created_at is None or not str(p.predicted_label or '').strip():
            continue
        combined.append({
            'type': 'approval',
            'id': p.id,
            'customer_id': p.customer_id,
            'name': p.name,
            'label': normalize_approval_label(p.predicted_label),
            'predicted_label': normalize_approval_label(p.predicted_label),
            'probability': p.probability,
            'risk_score': None,
            'risk_category': 'Approved' if normalize_approval_label(p.predicted_label) == 'Approved' else 'Rejected',
            'approval_score': p.approval_score,
            '_sort_at': p.created_at,
        })

    combined.sort(key=lambda item: item['_sort_at'], reverse=True)
    return combined


def _state_get(state, key, default=None):
    if isinstance(state, dict):
        return state.get(key, default)
    return getattr(state, key, default)


def _state_set(state, key, value):
    if isinstance(state, dict):
        state[key] = value
    else:
        setattr(state, key, value)


def load_or_rebuild_model(model_path, features_path, retrain_func, state, model_attr, features_attr):
    if os.path.exists(model_path) and os.path.exists(features_path):
        try:
            with warnings.catch_warnings(record=True) as caught_warnings:
                warnings.simplefilter('always')
                model = joblib.load(model_path)
            has_compat_warning = any(isinstance(w.message, InconsistentVersionWarning) for w in caught_warnings)
            if model is not None and not has_compat_warning:
                with open(features_path, encoding='utf-8') as f:
                    features = [line.strip() for line in f.readlines() if line.strip()]
                _state_set(state, model_attr, model)
                _state_set(state, features_attr, features)
                return model
        except Exception:
            pass

    if os.getenv('VERCEL'):
        _state_set(state, model_attr, None)
        _state_set(state, features_attr, [])
        return None

    try:
        model = retrain_func()
        with open(features_path, encoding='utf-8') as f:
            features = [line.strip() for line in f.readlines() if line.strip()]
        _state_set(state, model_attr, model)
        _state_set(state, features_attr, features)
        return model
    except Exception:
        _state_set(state, model_attr, None)
        _state_set(state, features_attr, [])
        return None


def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')
    app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET', 'dev-secret')
    local_database_path = os.path.join(PROJECT_ROOT, 'instance', 'loan.db')
    default_database_path = os.path.join(tempfile.gettempdir(), 'loan.db') if os.getenv('VERCEL') else local_database_path
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL') or sqlite_url(default_database_path)
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = False
    
    # Enable CORS for API requests with credentials support
    CORS(app, 
         resources={r"/api/*": {
             "origins": ["http://localhost:5000", "http://127.0.0.1:5000", "http://localhost:3000"],
             "methods": ["GET", "POST", "OPTIONS"],
             "allow_headers": ["Content-Type"],
             "supports_credentials": True
         }}
    )
    
    db.init_app(app)

    model_path = resolve_project_path('MODEL_PATH', 'model/model.joblib')
    features_path = resolve_project_path('FEATURES_PATH', 'model/features.txt')
    default_csv_path = resolve_project_path('DEFAULT_CSV_PATH', 'model/loan_default_data.csv')
    approval_model_path = resolve_project_path('APPROVAL_MODEL_PATH', 'model/approval_model.joblib')
    approval_features_path = resolve_project_path('APPROVAL_FEATURES_PATH', 'model/approval_features.txt')
    approval_csv_path = resolve_project_path('APPROVAL_CSV_PATH', 'model/loan_approval_data.csv')
    app.config['MODEL_PATH'] = model_path
    app.config['FEATURES_PATH'] = features_path
    app.config['DEFAULT_CSV_PATH'] = default_csv_path
    app.config['APPROVAL_MODEL_PATH'] = approval_model_path
    app.config['APPROVAL_FEATURES_PATH'] = approval_features_path
    app.config['APPROVAL_CSV_PATH'] = approval_csv_path

    with app.app_context():
        db.create_all()
        cleanup_prediction_history()

    def load_model():
        if not hasattr(app, 'ml_model') or getattr(app, 'ml_model', None) is None:
            return load_or_rebuild_model(
                model_path=app.config['MODEL_PATH'],
                features_path=app.config['FEATURES_PATH'],
                retrain_func=lambda: generate_and_train_default_model(
                    n_samples=8000,
                    model_path=app.config['MODEL_PATH'],
                    features_path=app.config['FEATURES_PATH'],
                    csv_path=app.config['DEFAULT_CSV_PATH']
                ),
                state=app,
                model_attr='ml_model',
                features_attr='features'
            )
        return app.ml_model

    def load_approval_model():
        if not hasattr(app, 'approval_model') or getattr(app, 'approval_model', None) is None:
            return load_or_rebuild_model(
                model_path=app.config['APPROVAL_MODEL_PATH'],
                features_path=app.config['APPROVAL_FEATURES_PATH'],
                retrain_func=lambda: generate_and_train_approval_model(
                    n_samples=8000,
                    model_path=app.config['APPROVAL_MODEL_PATH'],
                    features_path=app.config['APPROVAL_FEATURES_PATH'],
                    csv_path=app.config['APPROVAL_CSV_PATH']
                ),
                state=app,
                model_attr='approval_model',
                features_attr='approval_features'
            )
        return app.approval_model

    @app.context_processor
    def inject_user():
        return dict(logged_in=('user_id' in session), is_admin=session.get('is_admin', False), user_name=session.get('user_name', ''))

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if request.method == 'POST':
            name = request.form['name']
            email = request.form['email']
            password = request.form['password']
            if User.query.filter_by(email=email).first():
                return render_template('register.html', error='Email already registered')
            u = User(name=name, email=email)
            u.set_password(password)
            if email == os.getenv('ADMIN_EMAIL'):
                u.is_admin = True
            db.session.add(u)
            db.session.commit()
            return redirect(url_for('login'))
        return render_template('register.html')

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            email = request.form['email']
            password = request.form['password']
            u = User.query.filter_by(email=email).first()
            if not u or not u.check_password(password):
                return render_template('login.html', error='Invalid credentials')
            session['user_id'] = u.id
            session['user_name'] = u.name
            session['is_admin'] = u.is_admin
            return redirect(url_for('dashboard'))
        return render_template('login.html')

    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    def get_session_user_id():
        user_id = session.get('user_id')
        if user_id is None:
            return None

        if isinstance(user_id, str) and user_id.isdigit():
            user_id = int(user_id)

        user = db.session.get(User, user_id)
        if user is None:
            session.pop('user_id', None)
            session.pop('user_name', None)
            session.pop('is_admin', None)
            return None

        if session.get('user_id') != user.id:
            session['user_id'] = user.id
        return user.id

    def login_required(fn):
        from functools import wraps
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if get_session_user_id() is None:
                return redirect(url_for('login'))
            return fn(*args, **kwargs)
        return wrapper

    def admin_required(fn):
        from functools import wraps
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get('is_admin'):
                return 'Forbidden', 403
            return fn(*args, **kwargs)
        return wrapper

    @app.route('/dashboard')
    @login_required
    def dashboard():
        return render_template('dashboard.html')

    @app.route('/predict')
    @login_required
    def predict_page():
        return render_template('predict.html')

    @app.route('/predict_approval')
    @login_required
    def predict_approval_page():
        return render_template('predict_approval.html')

    @app.route('/history')
    @login_required
    def history_page():
        return render_template('history.html')



    def encode_employment_status(status):
        """Encode employment status to a numerical value for scoring."""
        status_map = {
            'salaried': 1.0,
            'employed': 1.0,
            'self-employed': 2.0,
            'self employed': 2.0,
            'unemployed': 0.0,
            'retired': 3.0,
            'student': 0.5,
            'freelancer': 2.0,
            'business': 2.0
        }
        status_str = str(status).strip().lower()
        return status_map.get(status_str, 0.0)

    def build_reason_explanations(features_dict, probability):
        """Generate explainable reasons for the model output without changing the UI contract."""
        reasons = []
        credit_score = float(features_dict.get('credit_score', 600))
        income = float(features_dict.get('income', 50000))
        debt_ratio = float(features_dict.get('debt_ratio', 0.3))
        previous_defaults = float(features_dict.get('previous_defaults', 0))
        existing_loans = float(features_dict.get('existing_loans', 0))
        loan_amount = float(features_dict.get('loan_amount', 200000))
        loan_tenure = float(features_dict.get('loan_tenure', 60))
        employment_status = str(features_dict.get('employment_status', 'Salaried')).strip().lower()

        if previous_defaults > 0:
            reasons.append({
                'feature': 'Previous Defaults',
                'importance': 0.95,
                'value': f'{int(previous_defaults)} prior default(s)'
            })
        if credit_score < 650:
            reasons.append({
                'feature': 'Credit Score',
                'importance': 0.90,
                'value': f'{int(credit_score)} (below the preferred range)'
            })
        if income < 45000:
            reasons.append({
                'feature': 'Income',
                'importance': 0.85,
                'value': f'₹{int(income):,}/month'
            })
        if debt_ratio > 0.40:
            reasons.append({
                'feature': 'Debt Ratio',
                'importance': 0.84,
                'value': f'{debt_ratio:.2f}'
            })
        if existing_loans >= 2:
            reasons.append({
                'feature': 'Existing Loans',
                'importance': 0.80,
                'value': f'{int(existing_loans)} current loan(s)'
            })
        loan_to_income = loan_amount / max(income, 1.0)
        if loan_to_income > 0.65:
            reasons.append({
                'feature': 'Loan Amount vs Income',
                'importance': 0.78,
                'value': f'{loan_to_income:.2f}x monthly income'
            })
        if loan_tenure > 72:
            reasons.append({
                'feature': 'Loan Tenure',
                'importance': 0.65,
                'value': f'{int(loan_tenure)} months'
            })
        if employment_status in ['unemployed', 'student']:
            reasons.append({
                'feature': 'Employment Stability',
                'importance': 0.76,
                'value': 'unstable or non-salaried employment'
            })
        elif employment_status in ['salaried', 'employed']:
            reasons.append({
                'feature': 'Employment Stability',
                'importance': 0.55,
                'value': 'stable employment profile'
            })

        if not reasons:
            reasons.append({
                'feature': 'Profile Balance',
                'importance': 0.70,
                'value': 'Overall risk appears balanced.'
            })

        return reasons[:5]

    def calculate_risk_category_and_score(proba):
        """Calculate risk category and score from probability using a 0-100 scale."""
        score = int(round(min(100, max(0, proba * 100))))

        if proba < 0.20:
            category = 'Very Low'
        elif proba < 0.40:
            category = 'Low'
        elif proba < 0.60:
            category = 'Moderate'
        elif proba < 0.80:
            category = 'High'
        else:
            category = 'Very High'

        return category, score

    @app.route('/api/predict', methods=['POST'])
    @login_required
    def api_predict():
        model = load_model()
        if model is None:
            return jsonify({'error': 'Model not available'}), 500

        payload = request.get_json() or request.form.to_dict()
        current_user_id = get_session_user_id()
        features = app.features
        
        # Build feature vector with proper encoding
        x = []
        features_dict = {}
        
        for f in features:
            val = payload.get(f)
            
            # Special handling for employment_status
            if f == 'employment_status':
                encoded_val = encode_employment_status(val)
                x.append(encoded_val)
                features_dict[f] = encoded_val
            else:
                # Convert to float, default to 0 if invalid
                try:
                    float_val = float(val)
                    x.append(float_val)
                    features_dict[f] = float_val
                except (ValueError, TypeError):
                    x.append(0.0)
                    features_dict[f] = 0.0

        # Get model prediction using the same feature order as training.
        try:
            feature_frame = create_default_feature_frame(features_dict)
            raw_proba = float(model.predict_proba(feature_frame)[0][1])
        except Exception:
            feature_frame = pd.DataFrame([dict(zip(features, x))])
            raw_proba = float(model.predict_proba(feature_frame)[0][1])

        adjusted_proba = compute_default_probability(feature_frame, raw_proba)

        # Determine label based on calibrated probability.
        label = 'Default' if adjusted_proba >= 0.75 else 'Non-Default'

        # Calculate risk category and score.
        category, score = calculate_risk_category_and_score(adjusted_proba)

        reasons = build_reason_explanations(features_dict, adjusted_proba)

        # Store prediction in database
        if current_user_id is None:
            return jsonify({'error': 'Please sign in again and try the assessment.'}), 401

        pred = Prediction(
            user_id=current_user_id,
            customer_id=payload.get('customer_id'),
            name=payload.get('name'),
            features=json.dumps(features_dict),
            predicted_label=label,
            probability=adjusted_proba,
            risk_score=score,
            risk_category=category
        )
        db.session.add(pred)
        db.session.commit()

        return jsonify({
            'label': label,
            'probability': round(adjusted_proba, 4),
            'risk_score': score,
            'risk_category': category,
            'reasons': reasons,
            'prediction_id': pred.id,
            'rule_based_override': False,
            'risk_factors': []
        })

    def encode_approval_features(payload):
        """Convert approval form payload into numeric features for the trained model."""
        employment_map = {
            'salaried': 1.0,
            'employed': 1.0,
            'self-employed': 2.0,
            'self employed': 2.0,
            'unemployed': 0.0,
            'student': 0.5
        }
        purpose_map = {
            'home': 0,
            'personal': 1,
            'education': 2,
            'business': 3,
            'vehicle': 4,
            'other': 5
        }

        def parse_float(key, fallback=0.0):
            try:
                return float(payload.get(key, fallback) or fallback)
            except (TypeError, ValueError):
                return float(fallback)

        employment_status = str(payload.get('employment_status', 'Salaried')).strip().lower()
        purpose_of_loan = str(payload.get('purpose_of_loan', 'Other')).strip().lower()

        monthly_income = parse_float('monthly_income', payload.get('income', 0))
        loan_amount_requested = parse_float('loan_amount_requested', payload.get('loan_amount', 0))
        existing_loan_amount = parse_float('existing_loan_amount', payload.get('existing_emi', payload.get('existing_loans', 0)))
        loan_tenure_months = parse_float('loan_tenure_months', payload.get('loan_tenure', 36))

        return {
            'age': parse_float('age', 35),
            'monthly_income': monthly_income,
            'employment_status': employment_map.get(employment_status, 0.0),
            'years_of_employment': parse_float('years_of_employment', 0),
            'credit_score': parse_float('credit_score', 600),
            'existing_loan_amount': existing_loan_amount,
            'loan_amount_requested': loan_amount_requested,
            'loan_tenure_months': loan_tenure_months,
            'purpose_of_loan': purpose_map.get(purpose_of_loan, 5)
        }

    def apply_approval_overrides(features_dict, model_proba):
        """Ensure financially strong applicants are not rejected by conservative model predictions."""
        income = float(features_dict.get('monthly_income', 0))
        credit_score = float(features_dict.get('credit_score', 0))
        existing = float(features_dict.get('existing_loan_amount', 0))
        loan_amount = float(features_dict.get('loan_amount_requested', 0))
        years_emp = float(features_dict.get('years_of_employment', 0))

        if income <= 0:
            return 0.0, False, ['monthly_income_missing']

        # Strong applicant override: high income + high credit + low obligations + stable employment
        strong_applicant = (
            income >= 70000 and
            credit_score >= 720 and
            existing <= 0.5 * income and
            loan_amount <= 8 * income and
            years_emp >= 2
        )

        if strong_applicant:
            # Boost probability to a high approval probability so model doesn't reject
            return max(model_proba, 0.85), True, ['strong_applicant_override']

        return model_proba, False, []

    def approval_reasons(features, decision, probability):
        reasons = []
        if features['monthly_income'] <= 0:
            reasons.append('No monthly income provided')
        if features['credit_score'] < 620:
            reasons.append('Low credit score')
        if features['monthly_income'] < 30000:
            reasons.append('Lower monthly income')
        if features['existing_loan_amount'] > features['monthly_income']:
            reasons.append('High existing obligations')
        if features['loan_amount_requested'] > features['monthly_income'] * 10:
            reasons.append('Loan request is large relative to income')
        if features['years_of_employment'] < 2:
            reasons.append('Limited employment history')
        if features['loan_tenure_months'] > 84:
            reasons.append('Long repayment duration')
        if not reasons:
            reasons.append('Profile matches strong approval patterns')

        if decision == 'Rejected' and probability > 0.45:
            reasons.insert(0, 'Rejection is cautious but marginally justified')
        if decision == 'Approved' and probability < 0.65:
            reasons.insert(0, 'Approval is conservative; profile is near the threshold')

        return reasons[:3]

    @app.route('/api/predict_approval', methods=['POST'])
    @login_required
    def api_predict_approval():
        """Loan approval prediction API powered by the trained Random Forest model."""
        payload = request.get_json() or request.form.to_dict()
        approval_model = load_approval_model()
        if approval_model is None:
            return jsonify({'error': 'Approval model unavailable'}), 500

        features_dict = encode_approval_features(payload)
        feature_vector = [
            features_dict['age'],
            features_dict['monthly_income'],
            features_dict['employment_status'],
            features_dict['years_of_employment'],
            features_dict['credit_score'],
            features_dict['existing_loan_amount'],
            features_dict['loan_amount_requested'],
            features_dict['loan_tenure_months'],
            features_dict['purpose_of_loan']
        ]

        # Use DataFrame with proper column names to avoid sklearn feature-name warnings
        try:
            df_feat = pd.DataFrame([{
                feat: feature_dict_val for feat, feature_dict_val in zip(app.approval_features, feature_vector)
            }])
            proba = float(approval_model.predict_proba(df_feat)[0][1])
        except Exception:
            proba = float(approval_model.predict_proba([feature_vector])[0][1])

        # Apply safety override for very strong applicants
        adjusted_proba, override_applied, override_reasons = apply_approval_overrides(features_dict, proba)

        decision = 'Approved' if adjusted_proba >= 0.5 else 'Rejected'
        confidence_score = round(adjusted_proba * 100, 1)
        reasons = approval_reasons(features_dict, decision, adjusted_proba)
        if override_applied:
            reasons.insert(0, 'Strong applicant — override applied')

        current_user_id = get_session_user_id()
        if current_user_id is None:
            return jsonify({'error': 'Please sign in again and try the approval prediction.'}), 401

        approval_pred = ApprovalPrediction(
            user_id=current_user_id,
            customer_id=payload.get('customer_id'),
            name=payload.get('name') or payload.get('full_name', 'Applicant'),
            features=json.dumps(features_dict),
            predicted_label=decision,
            probability=adjusted_proba,
            approval_score=int(round(confidence_score))
        )
        db.session.add(approval_pred)
        db.session.commit()

        response_label = 'Loan Approved' if decision == 'Approved' else 'Loan Rejected'
        return jsonify({
            'label': response_label,
            'probability': round(proba, 4),
            'confidence_score': confidence_score,
            'approval_score': int(round(confidence_score)),
            'reasons': reasons,
            'prediction_id': approval_pred.id
        })

    @app.route('/api/history')
    @login_required
    def api_history():
        cleanup_prediction_history()
        query = Prediction.query
        if not session.get('is_admin'):
            query = query.filter_by(user_id=session['user_id'])
        q = query.order_by(Prediction.created_at.desc()).limit(500).all()
        out = []
        for p in q:
            out.append({
                'id': p.id,
                'customer_id': p.customer_id,
                'name': p.name,
                'label': p.predicted_label,
                'probability': p.probability,
                'risk_score': p.risk_score,
                'risk_category': p.risk_category,
                'created_at': p.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        return jsonify(out)

    @app.route('/api/all_history')
    @login_required
    def api_all_history():
        cleanup_prediction_history()
        default_query = Prediction.query
        approval_query = ApprovalPrediction.query

        if not session.get('is_admin'):
            default_query = default_query.filter_by(user_id=session['user_id'])
            approval_query = approval_query.filter_by(user_id=session['user_id'])

        default_items = default_query.order_by(Prediction.created_at.desc()).limit(500).all()
        approval_items = approval_query.order_by(ApprovalPrediction.created_at.desc()).limit(500).all()

        out = []
        for p in default_items:
            out.append({
                'id': p.id,
                'customer_id': p.customer_id,
                'name': p.name,
                'label': p.predicted_label,
                'predicted_label': p.predicted_label,
                'probability': p.probability,
                'risk_score': p.risk_score,
                'risk_category': p.risk_category,
                'approval_score': None,
                'prediction_type': 'default',
                '_sort_at': p.created_at,
            })

        for p in approval_items:
            out.append({
                'id': p.id,
                'customer_id': p.customer_id,
                'name': p.name,
                'label': p.predicted_label,
                'predicted_label': p.predicted_label,
                'probability': p.probability,
                'risk_score': None,
                'risk_category': 'Approved' if p.predicted_label == 'Approved' else 'Rejected',
                'approval_score': p.approval_score,
                'prediction_type': 'approval',
                '_sort_at': p.created_at,
            })

        out.sort(key=lambda item: item['_sort_at'], reverse=True)
        for item in out:
            item['created_at'] = item['_sort_at'].strftime('%Y-%m-%d %H:%M')
            del item['_sort_at']

        return jsonify(out)

    @app.route('/api/approval_history')
    @login_required
    def api_approval_history():
        cleanup_prediction_history()
        query = ApprovalPrediction.query
        if not session.get('is_admin'):
            query = query.filter_by(user_id=session['user_id'])
        q = query.order_by(ApprovalPrediction.created_at.desc()).limit(500).all()
        out = []
        for p in q:
            out.append({
                'id': p.id,
                'customer_id': p.customer_id,
                'name': p.name,
                'label': p.predicted_label,
                'probability': p.probability,
                'approval_score': p.approval_score,
                'created_at': p.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        return jsonify(out)

    @app.route('/api/dashboard_data')
    @login_required
    def api_dashboard_data():
        cleanup_prediction_history()

        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        is_admin = session.get('is_admin', False)
        user_id = session.get('user_id')

        default_query = _get_scoped_history_query(Prediction, is_admin, user_id, from_date_str, to_date_str)
        approval_query = _get_scoped_history_query(ApprovalPrediction, is_admin, user_id, from_date_str, to_date_str)

        default_items = default_query.order_by(Prediction.created_at.desc()).all()
        approval_items = approval_query.order_by(ApprovalPrediction.created_at.desc()).all()
        combined_history = _build_combined_history(default_items, approval_items)

        total_predictions = len(default_items)

        average_risk_score = 0
        model_accuracy = 0
        high_risk_borrowers = 0
        low_risk_borrowers = 0
        medium_risk_borrowers = 0

        if total_predictions > 0:
            average_risk_score = sum(p.risk_score for p in default_items) / total_predictions
            high_confidence_count = sum(1 for p in default_items if p.probability > 0.7 or p.probability < 0.3)
            model_accuracy = (high_confidence_count / total_predictions) * 100 if total_predictions > 0 else 0
            high_risk_borrowers = sum(1 for p in default_items if normalize_risk_bucket(p.risk_category) == 'High')
            low_risk_borrowers = sum(1 for p in default_items if normalize_risk_bucket(p.risk_category) == 'Low')
            medium_risk_borrowers = sum(1 for p in default_items if normalize_risk_bucket(p.risk_category) == 'Medium')

        recent_predictions = []
        for item in combined_history[:10]:
            recent_predictions.append({
                'type': item['type'],
                'id': item['id'],
                'customer_id': item['customer_id'] or 'N/A',
                'name': item['name'] or 'Unknown',
                'predicted_label': item['predicted_label'],
                'probability': round(item['probability'] * 100, 1),
                'risk_score': item['risk_score'],
                'risk_category': item['risk_category'],
                'approval_score': item['approval_score'],
                'created_at': item['_sort_at'].strftime('%Y-%m-%d %H:%M'),
            })

        risk_distribution = {
            'Low': low_risk_borrowers,
            'Medium': medium_risk_borrowers,
            'High': high_risk_borrowers
        }

        trend_data = db.session.query(
            func.DATE(Prediction.created_at).label('date'),
            func.AVG(Prediction.probability).label('avg_prob'),
            func.COUNT(Prediction.id).label('count')
        )

        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
            trend_data = trend_data.filter(Prediction.created_at >= from_date)
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1)
            trend_data = trend_data.filter(Prediction.created_at < to_date)

        trend_data = trend_data.group_by(func.DATE(Prediction.created_at)).order_by('date').all()

        trend_labels = [str(t[0]) for t in trend_data]
        trend_values = [round(float(t[1]) * 100, 1) if t[1] else 0 for t in trend_data]

        defaults_count = sum(1 for p in default_items if p.predicted_label == 'Default')
        non_defaults_count = total_predictions - defaults_count

        total_approvals = len(approval_items)
        approved_count = sum(1 for p in approval_items if normalize_approval_label(p.predicted_label) == 'Approved')
        rejected_count = total_approvals - approved_count
        avg_approval_score = sum(p.approval_score for p in approval_items) / total_approvals if total_approvals > 0 else 0

        return jsonify({
            'total_predictions': total_predictions,
            'average_risk_score': round(average_risk_score, 1),
            'model_accuracy': round(model_accuracy, 1),
            'high_risk_borrowers': high_risk_borrowers,
            'low_risk_borrowers': low_risk_borrowers,
            'medium_risk_borrowers': medium_risk_borrowers,
            'recent_predictions': recent_predictions,
            'risk_distribution': risk_distribution,
            'prediction_trend': {
                'labels': trend_labels,
                'values': trend_values
            },
            'default_vs_non_default': {
                'defaults': defaults_count,
                'non_defaults': non_defaults_count
            },
            'total_approvals': total_approvals,
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'avg_approval_score': round(avg_approval_score, 1),
            'approval_vs_rejection': {
                'approved': approved_count,
                'rejected': rejected_count
            }
        })

    @app.route('/api/export_pdf', methods=['GET'])
    @login_required
    def api_export_pdf_route():
        """Export predictions as PDF with selected date range"""
        from_date_str = request.args.get('from_date')
        to_date_str = request.args.get('to_date')
        
        query = Prediction.query
        if not session.get('is_admin'):
            query = query.filter_by(user_id=session['user_id'])
        
        if from_date_str:
            from_date = datetime.strptime(from_date_str, '%Y-%m-%d')
            query = query.filter(Prediction.created_at >= from_date)
        if to_date_str:
            to_date = datetime.strptime(to_date_str, '%Y-%m-%d') + timedelta(days=1)
            query = query.filter(Prediction.created_at < to_date)
        
        predictions = query.order_by(Prediction.created_at.desc()).all()
        
        # Create PDF in memory
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                              rightMargin=0.5*inch, leftMargin=0.5*inch,
                              topMargin=0.75*inch, bottomMargin=0.75*inch)
        
        styles = getSampleStyleSheet()
        story = []
        
        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#4d80f5'),
            spaceAfter=6,
            alignment=1
        )
        story.append(Paragraph('RiskEdge | Loan Default Predictions Report', title_style))
        
        # Date Range and Export Info
        export_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        date_range_text = f"Date Range: {from_date_str or 'All'} to {to_date_str or 'All'} | Exported: {export_date}"
        info_style = ParagraphStyle(
            'Info',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#666666'),
            spaceAfter=12
        )
        story.append(Paragraph(date_range_text, info_style))
        
        # Summary Statistics
        total_records = len(predictions)
        avg_risk_score = round(sum(p.risk_score for p in predictions) / total_records, 1) if total_records > 0 else 0
        high_risk_count = sum(1 for p in predictions if p.risk_category == 'High')
        defaults_count = sum(1 for p in predictions if p.predicted_label == 'Default')
        
        summary_text = f"""
        <b>Summary Statistics:</b><br/>
        Total Records: {total_records} | High Risk: {high_risk_count} | 
        Average Risk Score: {avg_risk_score} | Defaults: {defaults_count}
        """
        story.append(Paragraph(summary_text, info_style))
        story.append(Spacer(1, 0.2*inch))
        
        # Table Data
        table_data = [['Customer ID', 'Customer Name', 'Prediction', 'Risk Category', 'Risk Score', 'Probability %', 'Created Date']]
        
        for p in predictions[:100]:  # Limit to 100 rows per PDF
            table_data.append([
                str(p.customer_id or 'N/A')[:15],
                str(p.name or 'Unknown')[:20],
                p.predicted_label,
                p.risk_category,
                str(p.risk_score),
                f"{round(p.probability * 100, 1)}%",
                p.created_at.strftime('%Y-%m-%d %H:%M')
            ])
        
        # Create table with styling
        table = Table(table_data, colWidths=[1.1*inch, 1.2*inch, 0.9*inch, 1*inch, 0.8*inch, 0.9*inch, 1.1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4d80f5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
        ]))
        
        story.append(table)
        
        # Build PDF
        doc.build(story)
        buffer.seek(0)
        
        return send_file(
            buffer,
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f'loan_predictions_{datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf'
        )
    @app.route('/api/history_search')
    @login_required
    def api_history_search():
        """Search predictions by customer name, ID, or risk category"""
        query = request.args.get('q', '').strip()
        risk_filter = request.args.get('risk', '').strip()
        limit = min(int(request.args.get('limit', 100)), 500)
        
        q = Prediction.query
        
        if query:
            q = q.filter(
                (Prediction.name.ilike(f'%{query}%')) |
                (Prediction.customer_id.ilike(f'%{query}%'))
            )
        
        if risk_filter and risk_filter in ['Low', 'Medium', 'High']:
            q = q.filter_by(risk_category=risk_filter)
        
        results = q.order_by(Prediction.created_at.desc()).limit(limit).all()
        
        out = []
        for p in results:
            out.append({
                'id': p.id,
                'customer_id': p.customer_id,
                'name': p.name,
                'label': p.predicted_label,
                'probability': p.probability,
                'risk_score': p.risk_score,
                'risk_category': p.risk_category,
                'created_at': p.created_at.strftime('%Y-%m-%d %H:%M'),
            })
        return jsonify(out)

    @app.route('/api/prediction/<int:id>/explain')
    @login_required
    def api_prediction_explain(id):
        """Get detailed explanation for a specific prediction"""
        pred = Prediction.query.get_or_404(id)
        # Ensure user can only access their own predictions unless they are admin
        if not session.get('is_admin') and pred.user_id != session['user_id']:
            return jsonify({'error': 'Unauthorized'}), 403
        model = load_model()
        
        try:
            features_dict = json.loads(pred.features)
            feature_values = [features_dict.get(f, 0) for f in app.features]
        except:
            feature_values = []
        
        reasons = []
        if hasattr(model, 'feature_importances_'):
            fi = model.feature_importances_
            pairs = list(zip(app.features, fi, feature_values))
            top_contributors = sorted(pairs, key=lambda p: p[1] * abs(p[2]), reverse=True)[:5]
            for name, importance, value in top_contributors:
                reasons.append({
                    'feature': name,
                    'importance': float(importance),
                    'value': float(value),
                    'contribution': float(importance * abs(value))
                })
        
        return jsonify({
            'prediction_id': id,
            'customer_id': pred.customer_id,
            'name': pred.name,
            'predicted_label': pred.predicted_label,
            'probability': pred.probability,
            'risk_score': pred.risk_score,
            'risk_category': pred.risk_category,
            'created_at': pred.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            'features': features_dict if 'features_dict' in locals() else {},
            'top_contributing_factors': reasons
        })

    @app.route('/admin')
    @login_required
    @admin_required
    def admin_panel():
        return render_template('admin.html')

    @app.route('/api/admin/delete/<int:id>', methods=['POST'])
    @login_required
    @admin_required
    def admin_delete(id):
        p = Prediction.query.get_or_404(id)
        db.session.delete(p)
        db.session.commit()
        return jsonify({'status': 'ok'})

    return app


app = create_app()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
