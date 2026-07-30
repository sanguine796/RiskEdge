import os
import unittest

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app, db
from models import User, Prediction, ApprovalPrediction


class ApprovalFormAPITest(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

        with self.app.app_context():
            db.drop_all()
            db.create_all()
            user = User(name='Test User', email='approval@example.com')
            user.set_password('secret123')
            db.session.add(user)
            db.session.commit()

    def test_approval_endpoint_accepts_new_fields_and_returns_approved_label(self):
        self.client.post('/login', data={
            'email': 'approval@example.com',
            'password': 'secret123'
        }, follow_redirects=False)

        payload = {
            'name': 'Jane Doe',
            'age': 32,
            'employment_status': 'Salaried',
            'years_of_employment': 7,
            'monthly_income': 85000,
            'credit_score': 760,
            'existing_loan_amount': 12000,
            'loan_amount_requested': 400000,
            'loan_tenure_months': 60,
            'purpose_of_loan': 'Home'
        }

        response = self.client.post('/api/predict_approval', json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertIn(data['label'], ['Loan Approved', 'Approved'])
        self.assertGreaterEqual(data['approval_score'], 0)
        self.assertLessEqual(data['approval_score'], 100)

    def test_zero_monthly_income_is_rejected(self):
        self.client.post('/login', data={
            'email': 'approval@example.com',
            'password': 'secret123'
        }, follow_redirects=False)

        payload = {
            'name': 'Zero Income Applicant',
            'age': 30,
            'employment_status': 'Salaried',
            'years_of_employment': 3,
            'monthly_income': 0,
            'credit_score': 680,
            'existing_loan_amount': 0,
            'loan_amount_requested': 100000,
            'loan_tenure_months': 24,
            'purpose_of_loan': 'Personal'
        }

        response = self.client.post('/api/predict_approval', json=payload)
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(data['label'], 'Loan Rejected')
        self.assertLessEqual(data['approval_score'], 50)

    def test_all_history_includes_default_and_approval_predictions(self):
        self.client.post('/login', data={
            'email': 'approval@example.com',
            'password': 'secret123'
        }, follow_redirects=False)

        with self.app.app_context():
            user = User.query.filter_by(email='approval@example.com').first()
            db.session.add_all([
                Prediction(
                    user_id=user.id,
                    customer_id='D-001',
                    name='Default Customer',
                    features='{}',
                    predicted_label='Default',
                    probability=0.72,
                    risk_score=72,
                    risk_category='High'
                ),
                ApprovalPrediction(
                    user_id=user.id,
                    customer_id='A-001',
                    name='Approval Customer',
                    features='{}',
                    predicted_label='Approved',
                    probability=0.83,
                    approval_score=83
                )
            ])
            db.session.commit()

        response = self.client.get('/api/all_history')
        self.assertEqual(response.status_code, 200)

        data = response.get_json()
        self.assertEqual(len(data), 2)
        labels = {item.get('label') or item.get('predicted_label') for item in data}
        self.assertIn('Default', labels)
        self.assertIn('Approved', labels)


if __name__ == '__main__':
    unittest.main()
