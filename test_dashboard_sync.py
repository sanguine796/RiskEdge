import os
from datetime import datetime, timedelta

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app, db
from models import ApprovalPrediction, Prediction, User


def test_dashboard_uses_stored_history_for_stats_and_recent_predictions():
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()

        user = User(name='Dashboard Tester', email='dashboard@example.com')
        user.set_password('password123')
        db.session.add(user)
        db.session.commit()

        default_prediction = Prediction(
            user_id=user.id,
            customer_id='CUST-1',
            name='Alice',
            features='{}',
            predicted_label='Default',
            probability=0.98,
            risk_score=98,
            risk_category='High',
            created_at=datetime.utcnow() - timedelta(minutes=5),
        )
        approval_prediction = ApprovalPrediction(
            user_id=user.id,
            customer_id='CUST-2',
            name='Bob',
            features='{}',
            predicted_label='Approved',
            probability=0.95,
            approval_score=95,
            created_at=datetime.utcnow(),
        )
        db.session.add_all([default_prediction, approval_prediction])
        db.session.commit()

        with app.test_client() as client:
            with client.session_transaction() as session:
                session['user_id'] = user.id
                session['is_admin'] = True
                session['user_name'] = user.name

            response = client.get('/api/dashboard_data')

            assert response.status_code == 200
            payload = response.get_json()
            assert payload['total_predictions'] == 1
            assert payload['total_approvals'] == 1
            assert payload['approved_count'] == 1
            assert payload['rejected_count'] == 0
            assert len(payload['recent_predictions']) == 2
            assert payload['recent_predictions'][0]['type'] == 'approval'
            assert payload['recent_predictions'][0]['predicted_label'] == 'Approved'
