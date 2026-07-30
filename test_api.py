import sys
sys.path.insert(0, '.')
from app import create_app, db
from models import User
import json

app = create_app()

with app.test_client() as client:
    with app.app_context():
        # Try to get the user we created
        user = User.query.filter_by(email='testuser@example.com').first()
        print(f"User found: {user}")
        if user:
            print(f"User ID: {user.id}, Name: {user.name}")
        
        # Now test prediction API (without auth - should fail)
        print("\n=== Testing prediction API without auth ===")
        response = client.post('/api/predict',
            json={
                'name': 'Test Customer',
                'age': 35,
                'employment_status': 'Salaried',
                'income': 50000,
                'credit_score': 750,
                'debt_ratio': 0.3,
                'previous_defaults': 0,
                'existing_loans': 2,
                'loan_amount': 300000,
                'loan_tenure': 60,
                'customer_id': 'CUST001'
            }
        )
        
        print(f"API Response Status: {response.status_code}")
        print(f"Response Location: {response.location}")
        
        # Now test with proper login session
        print("\n=== Testing prediction API with auth ===")
        
        # First, login
        login_response = client.post('/login', data={
            'email': 'testuser@example.com',
            'password': 'password123'
        }, follow_redirects=False)
        print(f"Login Response Status: {login_response.status_code}")
        
        # Now make the prediction request with the session
        response = client.post('/api/predict',
            json={
                'name': 'Test Customer',
                'age': 35,
                'employment_status': 'Salaried',
                'income': 50000,
                'credit_score': 750,
                'debt_ratio': 0.3,
                'previous_defaults': 0,
                'existing_loans': 2,
                'loan_amount': 300000,
                'loan_tenure': 60,
                'customer_id': 'CUST001'
            }
        )
        
        print(f"API Response Status: {response.status_code}")
        print(f"Response Data (first 1000 chars):")
        resp_text = response.get_data(as_text=True)
        print(resp_text[:1000])
        
        if response.status_code == 200:
            try:
                data = response.get_json()
                print(f"\nPrediction Result:")
                print(f"  Label: {data.get('label')}")
                print(f"  Probability: {data.get('probability')}")
                print(f"  Risk Score: {data.get('risk_score')}")
                print(f"  Risk Category: {data.get('risk_category')}")
                print(f"\nSuccess! Prediction saved with ID: {data.get('prediction_id')}")
            except Exception as e:
                print(f"Could not parse JSON: {e}")
        else:
            print(f"Error: Status {response.status_code}")
