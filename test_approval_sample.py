import joblib
import os
import pandas as pd

MODEL_PATH = os.path.join(os.path.dirname(__file__), 'model', 'approval_model.joblib')
FEATURES_PATH = os.path.join(os.path.dirname(__file__), 'model', 'approval_features.txt')

model = joblib.load(MODEL_PATH)
with open(FEATURES_PATH) as f:
    features = [l.strip() for l in f.readlines() if l.strip()]

def predict(sample):
    df = pd.DataFrame([{f: sample.get(f, 0) for f in features}])
    proba = model.predict_proba(df)[0][1]
    return proba

strong = {
    'age': 38,
    'monthly_income': 90000,
    'employment_status': 1.0,
    'years_of_employment': 6,
    'credit_score': 740,
    'existing_loan_amount': 20000,
    'loan_amount_requested': 300000,
    'loan_tenure_months': 60,
    'purpose_of_loan': 0
}

weak = {
    'age': 28,
    'monthly_income': 15000,
    'employment_status': 0.0,
    'years_of_employment': 0,
    'credit_score': 420,
    'existing_loan_amount': 20000,
    'loan_amount_requested': 200000,
    'loan_tenure_months': 84,
    'purpose_of_loan': 1
}

borderline = {
    'age': 30,
    'monthly_income': 40000,
    'employment_status': 1.0,
    'years_of_employment': 2,
    'credit_score': 640,
    'existing_loan_amount': 10000,
    'loan_amount_requested': 200000,
    'loan_tenure_months': 60,
    'purpose_of_loan': 1
}

print('Strong proba:', predict(strong))
print('Weak proba:', predict(weak))
print('Borderline proba:', predict(borderline))
