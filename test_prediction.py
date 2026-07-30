import requests
import json
import unittest

from train_model import (
    compute_approval_decision,
    compute_default_risk_category,
    compute_default_probability,
    create_default_feature_frame,
)

# Create a session for authentication
session = requests.Session()

# First, register a test user
register_data = {'name': 'Test User', 'email': 'testuser@example.com', 'password': 'testpass'}
response = session.post('http://127.0.0.1:5000/register', data=register_data, allow_redirects=False)
print('Register:', response.status_code)

# Login
login_data = {'email': 'testuser@example.com', 'password': 'testpass'}
response = session.post('http://127.0.0.1:5000/login', data=login_data, allow_redirects=False)
print('Login:', response.status_code)

# Test extreme-risk borrower prediction
extreme_risk_data = {
    'customer_id': 'EXT001',
    'name': 'Extreme Risk Borrower',
    'age': 35,
    'income': 15000,
    'employment_status': 'unemployed',
    'credit_score': 400,
    'loan_amount': 500000,
    'loan_tenure': 60,
    'debt_ratio': 0.7,
    'previous_defaults': 1,
    'existing_loans': 5
}

response = session.post('http://127.0.0.1:5000/api/predict', json=extreme_risk_data)
print('Prediction Status:', response.status_code)
result = response.json()
print('\nPrediction Result:')
print(json.dumps(result, indent=2))

# Test low-risk borrower for comparison
print('\n' + '='*80)
print('Testing Low-Risk Borrower for Comparison:')
print('='*80 + '\n')

low_risk_data = {
    'customer_id': 'LOW001',
    'name': 'Low Risk Borrower',
    'age': 40,
    'income': 150000,
    'employment_status': 'salaried',
    'credit_score': 750,
    'loan_amount': 50000,
    'loan_tenure': 60,
    'debt_ratio': 0.2,
    'previous_defaults': 0,
    'existing_loans': 1
}

response = session.post('http://127.0.0.1:5000/api/predict', json=low_risk_data)
print('Prediction Status:', response.status_code)
result = response.json()
print('\nPrediction Result:')
print(json.dumps(result, indent=2))


class RuleBasedModelTests(unittest.TestCase):
    def test_approval_decision_matches_banking_rules(self):
        strong_profile = {
            'credit_score': 760,
            'employment_status': 'Salaried',
            'monthly_income': 95000,
            'years_of_employment': 6,
            'existing_loan_amount': 15000,
            'loan_amount_requested': 280000,
        }
        weak_profile = {
            'credit_score': 520,
            'employment_status': 'Unemployed',
            'monthly_income': 12000,
            'years_of_employment': 0.5,
            'existing_loan_amount': 85000,
            'loan_amount_requested': 300000,
        }
        borderline_profile = {
            'credit_score': 690,
            'employment_status': 'Self-Employed',
            'monthly_income': 42000,
            'years_of_employment': 2.5,
            'existing_loan_amount': 18000,
            'loan_amount_requested': 220000,
        }

        self.assertEqual(compute_approval_decision(strong_profile), 'Approved')
        self.assertEqual(compute_approval_decision(weak_profile), 'Rejected')
        self.assertIn(compute_approval_decision(borderline_profile), ['Approved', 'Rejected'])

    def test_default_risk_category_matches_banking_rules(self):
        low_risk_profile = {
            'credit_score': 780,
            'income': 120000,
            'employment_status': 'Salaried',
            'loan_amount': 120000,
            'debt_ratio': 0.08,
            'previous_defaults': 0,
            'existing_loans': 1,
        }
        very_high_risk_profile = {
            'credit_score': 420,
            'income': 18000,
            'employment_status': 'Unemployed',
            'loan_amount': 260000,
            'debt_ratio': 1.4,
            'previous_defaults': 3,
            'existing_loans': 5,
        }

        self.assertEqual(compute_default_risk_category(low_risk_profile), 'Low')
        self.assertEqual(compute_default_risk_category(very_high_risk_profile), 'Very High')

    def test_stable_applicant_probability_stays_below_moderate_threshold(self):
        stable_profile = {
            'age': 50,
            'income': 50000,
            'employment_status': 'Employed',
            'credit_score': 650,
            'loan_amount': 400000,
            'loan_tenure': 60,
            'debt_ratio': 0.5,
            'previous_defaults': 0,
            'existing_loans': 0,
        }

        feature_frame = create_default_feature_frame(stable_profile)
        probability = compute_default_probability(feature_frame, 0.88)

        self.assertLess(probability, 0.5)
        self.assertNotEqual(compute_default_risk_category(stable_profile), 'Very High')

    def test_risky_applicant_probability_stays_high(self):
        risky_profile = {
            'age': 32,
            'income': 18000,
            'employment_status': 'Unemployed',
            'credit_score': 420,
            'loan_amount': 260000,
            'loan_tenure': 60,
            'debt_ratio': 1.4,
            'previous_defaults': 3,
            'existing_loans': 5,
        }

        feature_frame = create_default_feature_frame(risky_profile)
        probability = compute_default_probability(feature_frame, 0.2)

        self.assertGreater(probability, 0.8)
        self.assertEqual(compute_default_risk_category(risky_profile), 'Very High')


if __name__ == '__main__':
    unittest.main()
