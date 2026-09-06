"""Generate realistic synthetic banking datasets and train the approval/default models."""
import os
import warnings
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import train_test_split
from sklearn.utils import shuffle
from sklearn.exceptions import InconsistentVersionWarning

# Suppress sklearn version warnings
warnings.filterwarnings('ignore', category=InconsistentVersionWarning)

MODEL_DIR = os.path.join(os.path.dirname(__file__), 'model')
os.makedirs(MODEL_DIR, exist_ok=True)

EMPLOYMENT_CHOICES = ['Salaried', 'Self-Employed', 'Unemployed', 'Student']
PURPOSE_CHOICES = ['Home', 'Personal', 'Education', 'Business', 'Vehicle', 'Other']
EMPLOYMENT_MAP = {'Salaried': 1.0, 'Self-Employed': 2.0, 'Unemployed': 0.0, 'Student': 0.5}
PURPOSE_MAP = {purpose: idx for idx, purpose in enumerate(PURPOSE_CHOICES)}


def _encode_employment_status(status):
    if isinstance(status, (int, float)) and not isinstance(status, bool):
        if abs(float(status) - 1.0) < 1e-9:
            return 1.0
        if abs(float(status) - 2.0) < 1e-9:
            return 2.0
        if abs(float(status) - 0.0) < 1e-9:
            return 0.0
        if abs(float(status) - 0.5) < 1e-9:
            return 0.5

    status_key = str(status).strip().lower()
    status_map = {
        'salaried': 1.0,
        'employed': 1.0,
        'self-employed': 2.0,
        'self employed': 2.0,
        'unemployed': 0.0,
        'retired': 1.0,
        'student': 0.5,
        'freelancer': 2.0,
        'business': 2.0,
        '1': 1.0,
        '1.0': 1.0,
        '2': 2.0,
        '2.0': 2.0,
        '0': 0.0,
        '0.0': 0.0,
        '0.5': 0.5,
    }
    return status_map.get(status_key, 1.0)


def _normalize_employment_status(status):
    encoded = _encode_employment_status(status)
    reverse_map = {1.0: 'Salaried', 2.0: 'Self-Employed', 0.0: 'Unemployed', 0.5: 'Student'}
    return reverse_map.get(encoded, 'Salaried')

FEATURE_COLUMNS = [
    'age', 'monthly_income', 'employment_status', 'years_of_employment',
    'credit_score', 'existing_loan_amount', 'loan_amount_requested',
    'loan_tenure_months', 'purpose_of_loan'
]
TARGET_COLUMN = 'approved'

DEFAULT_FEATURE_COLUMNS = [
    'age', 'income', 'employment_status', 'credit_score',
    'loan_amount', 'loan_tenure', 'debt_ratio', 'previous_defaults', 'existing_loans'
]
DEFAULT_TARGET_COLUMN = 'defaulted'


def _coerce_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def compute_default_probability(feature_frame, raw_probability):
    """Calibrate a model probability into a realistic banking-style default probability."""
    if feature_frame is None or feature_frame.empty:
        return float(raw_probability)

    row = feature_frame.iloc[0]
    credit_score = _coerce_float(row.get('credit_score', 600))
    income = _coerce_float(row.get('income', 50000))
    debt_ratio = _coerce_float(row.get('debt_ratio', 0.3))
    previous_defaults = _coerce_int(row.get('previous_defaults', 0))
    existing_loans = _coerce_int(row.get('existing_loans', 0))
    loan_amount = _coerce_float(row.get('loan_amount', 200000))
    loan_tenure = _coerce_float(row.get('loan_tenure', 60))
    employment_status = _normalize_employment_status(row.get('employment_status', 'Salaried')).lower()

    adjusted = float(raw_probability)
    adjusted = min(0.98, max(0.01, adjusted))

    # Apply modest, interpretable adjustments so strong negative signals increase risk.
    # Stable profiles with good credit and income should not be pushed up artificially.
    strong_profile = (
        credit_score >= 650 and income >= 45000 and debt_ratio <= 0.55 and previous_defaults == 0 and existing_loans <= 1
    )

    if strong_profile:
        adjusted -= 0.25

    if previous_defaults >= 2:
        adjusted += 0.16
    elif previous_defaults == 1:
        adjusted += 0.07

    if existing_loans >= 4:
        adjusted += 0.10
    elif existing_loans >= 2:
        adjusted += 0.05

    if credit_score < 550:
        adjusted += 0.10
    elif credit_score < 650:
        adjusted += 0.04
    elif credit_score >= 750:
        adjusted -= 0.04

    if income < 25000:
        adjusted += 0.08
    elif income < 45000:
        adjusted += 0.03
    elif income >= 90000:
        adjusted -= 0.03

    if debt_ratio >= 0.75:
        adjusted += 0.10
    elif debt_ratio >= 0.40:
        adjusted += 0.03
    elif debt_ratio <= 0.15:
        adjusted -= 0.03

    loan_to_income = loan_amount / max(income, 1.0)
    if loan_to_income > 1.20:
        adjusted += 0.02

    if loan_tenure > 72:
        adjusted += 0.02

    if employment_status in ['unemployed', 'student']:
        adjusted += 0.06
    elif employment_status == 'self-employed':
        adjusted += 0.01
    elif employment_status in ['salaried', 'employed']:
        adjusted -= 0.04

    return round(min(0.98, max(0.01, adjusted)), 4)


def compute_default_risk_category(profile_or_probability):
    """Map a calibrated probability to a realistic risk band."""
    if isinstance(profile_or_probability, dict):
        feature_frame = create_default_feature_frame(profile_or_probability)
        probability = compute_default_probability(feature_frame, 0.5)
    else:
        probability = float(profile_or_probability)

    if probability <= 0.20:
        return 'Very Low'
    if probability <= 0.40:
        return 'Low'
    if probability <= 0.60:
        return 'Moderate'
    if probability <= 0.80:
        return 'High'
    return 'Very High'


def create_default_feature_frame(profile):
    """Create a DataFrame with the same feature order used during training."""
    payload = dict(profile or {})
    row = {}
    for column in DEFAULT_FEATURE_COLUMNS:
        if column == 'employment_status':
            row[column] = _encode_employment_status(payload.get(column, 'Salaried'))
        else:
            row[column] = _coerce_float(payload.get(column, 0), default=0.0)
    return pd.DataFrame([row], columns=DEFAULT_FEATURE_COLUMNS)


def compute_approval_decision(profile):
    """Simple rule-based approval heuristic for tests and consistency."""
    credit_score = _coerce_float(profile.get('credit_score', 600))
    monthly_income = _coerce_float(profile.get('monthly_income', profile.get('income', 0)))
    employment_status = str(profile.get('employment_status', 'Salaried')).strip().lower()
    years_of_employment = _coerce_float(profile.get('years_of_employment', 0))
    existing_loan_amount = _coerce_float(profile.get('existing_loan_amount', 0))
    loan_amount_requested = _coerce_float(profile.get('loan_amount_requested', profile.get('loan_amount', 0)))

    score = 0.0
    if credit_score >= 700:
        score += 4.2
    elif credit_score >= 650:
        score += 1.8
    else:
        score -= 2.8

    if employment_status in ['salaried', 'self-employed', 'employed']:
        score += 1.8
    elif employment_status == 'student':
        score -= 1.2
    else:
        score -= 2.6

    if monthly_income >= 70000:
        score += 2.4
    elif monthly_income >= 35000:
        score += 1.1
    else:
        score -= 1.8

    if years_of_employment >= 5:
        score += 1.3
    elif years_of_employment >= 2:
        score += 0.5
    else:
        score -= 0.8

    debt_ratio = existing_loan_amount / max(monthly_income, 1.0)
    if debt_ratio <= 0.20:
        score += 1.6
    elif debt_ratio <= 0.45:
        score += 0.4
    elif debt_ratio > 1.0:
        score -= 2.4

    loan_to_income = loan_amount_requested / max(monthly_income, 1.0)
    if loan_to_income <= 4:
        score += 1.4
    elif loan_to_income <= 6:
        score += 0.3
    elif loan_to_income > 8:
        score -= 2.2

    return 'Approved' if score >= 0 else 'Rejected'


def generate_loan_approval_dataset(n=7000, random_state=42):
    rng = np.random.default_rng(random_state)
    rows = []

    for _ in range(n):
        employment_status = rng.choice(EMPLOYMENT_CHOICES, p=[0.45, 0.22, 0.18, 0.15])

        if employment_status == 'Salaried':
            age = float(np.clip(rng.normal(39, 8), 21, 67))
            monthly_income = float(np.clip(rng.normal(76000, 18000), 12000, 240000))
            years_of_employment = float(np.clip(rng.normal(7, 4), 0, 40))
        elif employment_status == 'Self-Employed':
            age = float(np.clip(rng.normal(42, 9), 23, 68))
            monthly_income = float(np.clip(rng.normal(68000, 22000), 10000, 220000))
            years_of_employment = float(np.clip(rng.normal(6, 5), 0, 40))
        elif employment_status == 'Unemployed':
            age = float(np.clip(rng.normal(36, 10), 20, 65))
            monthly_income = float(np.clip(rng.normal(18000, 7000), 3000, 60000))
            years_of_employment = float(np.clip(rng.normal(0.8, 1.4), 0, 20))
        else:
            age = float(np.clip(rng.normal(24, 4), 18, 35))
            monthly_income = float(np.clip(rng.normal(22000, 9000), 5000, 90000))
            years_of_employment = float(np.clip(rng.normal(1.2, 1.7), 0, 20))

        loan_tenure_months = int(rng.choice([12, 24, 36, 48, 60, 72, 84], p=[0.05, 0.15, 0.25, 0.20, 0.18, 0.10, 0.07]))
        purpose_of_loan = rng.choice(PURPOSE_CHOICES, p=[0.22, 0.23, 0.16, 0.18, 0.12, 0.09])

        base_credit = 620 + (monthly_income / 5000) * 1.4 + min(years_of_employment, 15) * 8
        if employment_status == 'Salaried':
            base_credit += 25
        elif employment_status == 'Self-Employed':
            base_credit += 10
        elif employment_status == 'Unemployed':
            base_credit -= 80
        elif employment_status == 'Student':
            base_credit -= 40
        credit_score = float(np.clip(rng.normal(base_credit, 42), 300, 850))

        target_emi = monthly_income * rng.choice([0.10, 0.15, 0.25, 0.35, 0.50], p=[0.25, 0.30, 0.20, 0.15, 0.10])
        existing_loan_amount = float(np.clip(rng.normal(target_emi, target_emi * 0.35), 0, 500000))
        loan_to_income_multiplier = rng.choice([2.5, 3.5, 4.5, 5.5, 7.0, 9.0, 12.0], p=[0.10, 0.18, 0.24, 0.20, 0.15, 0.08, 0.05])
        loan_amount_requested = float(np.clip(monthly_income * loan_to_income_multiplier, 5000, 1200000))

        monthly_income_nonzero = max(monthly_income, 1.0)
        debt_ratio = existing_loan_amount / monthly_income_nonzero
        loan_to_income = loan_amount_requested / monthly_income_nonzero

        approval_score = 0.0
        if credit_score >= 700:
            approval_score += 4.2
        elif credit_score >= 650:
            approval_score += 1.8
        else:
            approval_score -= 2.8

        if employment_status in ['Salaried', 'Self-Employed']:
            approval_score += 1.8
        elif employment_status == 'Student':
            approval_score -= 1.2
        else:
            approval_score -= 2.6

        if monthly_income >= 70000:
            approval_score += 2.4
        elif monthly_income >= 35000:
            approval_score += 1.1
        else:
            approval_score -= 1.8

        if years_of_employment >= 5:
            approval_score += 1.3
        elif years_of_employment >= 2:
            approval_score += 0.5
        else:
            approval_score -= 0.8

        if debt_ratio <= 0.20:
            approval_score += 1.6
        elif debt_ratio <= 0.45:
            approval_score += 0.4
        elif debt_ratio > 1.0:
            approval_score -= 2.4

        if loan_to_income <= 4:
            approval_score += 1.4
        elif loan_to_income <= 6:
            approval_score += 0.3
        elif loan_to_income > 8:
            approval_score -= 2.2

        if purpose_of_loan in ['Home', 'Education']:
            approval_score += 0.5
        if loan_tenure_months <= 60:
            approval_score += 0.2
        elif loan_tenure_months > 84:
            approval_score -= 0.7

        approval_score += rng.normal(0.0, 0.6)
        approval_prob = 1 / (1 + np.exp(-approval_score))
        approved = int(rng.random() < np.clip(approval_prob, 0.04, 0.96))

        rows.append({
            'age': age,
            'monthly_income': monthly_income,
            'employment_status': employment_status,
            'years_of_employment': years_of_employment,
            'credit_score': credit_score,
            'existing_loan_amount': existing_loan_amount,
            'loan_amount_requested': loan_amount_requested,
            'loan_tenure_months': loan_tenure_months,
            'purpose_of_loan': purpose_of_loan,
            'approved': int(approved),
            'decision': 'Approved' if approved else 'Rejected'
        })

    return shuffle(pd.DataFrame(rows), random_state=random_state)


def generate_loan_default_dataset(n=8000, random_state=42):
    rng = np.random.default_rng(random_state)
    rows = []

    for _ in range(n):
        employment_status = rng.choice(EMPLOYMENT_CHOICES, p=[0.42, 0.20, 0.18, 0.20])

        if employment_status == 'Salaried':
            age = float(np.clip(rng.normal(40, 9), 22, 68))
            income = float(np.clip(rng.normal(65000, 20000), 12000, 220000))
        elif employment_status == 'Self-Employed':
            age = float(np.clip(rng.normal(43, 10), 23, 70))
            income = float(np.clip(rng.normal(52000, 24000), 10000, 180000))
        elif employment_status == 'Unemployed':
            age = float(np.clip(rng.normal(36, 12), 20, 65))
            income = float(np.clip(rng.normal(15000, 7000), 3000, 60000))
        else:
            age = float(np.clip(rng.normal(23, 4), 18, 35))
            income = float(np.clip(rng.normal(18000, 8000), 5000, 90000))

        credit_score = float(np.clip(rng.normal(650 + (income / 18000) * 2.0 + (0 if employment_status in ['Salaried', 'Self-Employed'] else -35), 38), 300, 850))
        loan_amount = float(np.clip(rng.normal(income * rng.choice([0.25, 0.45, 0.65, 0.85, 1.10], p=[0.10, 0.25, 0.30, 0.20, 0.15]), income * 0.25), 1000, 1200000))
        existing_loans = int(np.clip(rng.poisson(1.2), 0, 8))
        existing_loan_amount = float(np.clip(loan_amount * 0.1 + income * (existing_loans / 8.0) * rng.choice([0.2, 0.5, 0.8], p=[0.35, 0.45, 0.20]), 0, 600000))
        debt_ratio = existing_loan_amount / max(income, 1.0)
        previous_defaults = int(np.clip(rng.poisson(0.55), 0, 5))
        loan_tenure = int(rng.choice([12, 24, 36, 48, 60, 72, 84], p=[0.08, 0.16, 0.20, 0.18, 0.18, 0.12, 0.08]))

        default_score = 0.0
        if credit_score < 550:
            default_score += 4.0
        elif credit_score < 650:
            default_score += 2.0
        elif credit_score >= 750:
            default_score -= 2.8

        if income < 25000:
            default_score += 2.2
        elif income < 45000:
            default_score += 0.8
        elif income >= 90000:
            default_score -= 1.2

        if debt_ratio >= 0.75:
            default_score += 4.2
        elif debt_ratio >= 0.40:
            default_score += 2.0
        elif debt_ratio <= 0.15:
            default_score -= 1.6

        if previous_defaults >= 3:
            default_score += 4.2
        elif previous_defaults == 2:
            default_score += 2.4
        elif previous_defaults == 1:
            default_score += 1.1

        if existing_loans >= 4:
            default_score += 2.6
        elif existing_loans >= 2:
            default_score += 1.0

        if employment_status in ['Unemployed', 'Student']:
            default_score += 1.8
        elif employment_status == 'Self-Employed':
            default_score += 0.6

        if loan_amount / max(income, 1.0) > 0.65:
            default_score += 1.5

        if loan_tenure > 72:
            default_score += 0.4

        default_score += rng.normal(0.0, 0.7)
        default_prob = 1 / (1 + np.exp(- (default_score - 0.1)))
        defaulted = int(rng.random() < np.clip(default_prob, 0.02, 0.98))

        risk_category = 'Low' if default_prob < 0.22 else 'Medium' if default_prob < 0.45 else 'High' if default_prob < 0.75 else 'Very High'

        rows.append({
            'age': age,
            'income': income,
            'employment_status': employment_status,
            'credit_score': credit_score,
            'loan_amount': loan_amount,
            'loan_tenure': loan_tenure,
            'debt_ratio': round(debt_ratio, 4),
            'previous_defaults': previous_defaults,
            'existing_loans': existing_loans,
            'defaulted': int(defaulted),
            'risk_category': risk_category,
        })

    return shuffle(pd.DataFrame(rows), random_state=random_state)


def prepare_training_data(df):
    data = df.copy()
    data['employment_status'] = data['employment_status'].map(EMPLOYMENT_MAP)
    data['purpose_of_loan'] = data['purpose_of_loan'].map(PURPOSE_MAP)
    feature_df = data[FEATURE_COLUMNS]
    target = data[TARGET_COLUMN]
    return feature_df, target


def prepare_default_training_data(df):
    data = df.copy()
    data['employment_status'] = data['employment_status'].map(EMPLOYMENT_MAP)
    feature_df = data[DEFAULT_FEATURE_COLUMNS]
    target = data[DEFAULT_TARGET_COLUMN]
    return feature_df, target


def generate_and_train_approval_model(
    n_samples=7000,
    model_path=None,
    features_path=None,
    csv_path=None,
    random_state=42
):
    if model_path is None:
        model_path = os.path.join(MODEL_DIR, 'approval_model.joblib')
    if features_path is None:
        features_path = os.path.join(MODEL_DIR, 'approval_features.txt')
    if csv_path is None:
        csv_path = os.path.join(MODEL_DIR, 'loan_approval_data.csv')

    print('Generating realistic loan approval data...')
    df = generate_loan_approval_dataset(n=n_samples, random_state=random_state)
    df.to_csv(csv_path, index=False)

    try:
        df['income_bin'] = pd.qcut(df['monthly_income'], q=4, labels=False, duplicates='drop')
    except Exception:
        df['income_bin'] = pd.cut(df['monthly_income'], bins=[0, 30000, 60000, 100000, 1e9], labels=False)

    groups = df.groupby(['employment_status', 'income_bin'])
    target_per_group = max(int(n_samples / (len(EMPLOYMENT_CHOICES) * 4)), 60)
    balanced = []
    for _, g in groups:
        balanced.append(g.sample(n=min(len(g), target_per_group), random_state=random_state) if len(g) >= target_per_group else g.sample(n=target_per_group, replace=True, random_state=random_state))
    balanced_df = shuffle(pd.concat(balanced, ignore_index=True), random_state=random_state)

    X, y = prepare_training_data(balanced_df)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=random_state)

    base_model = RandomForestClassifier(
        n_estimators=300,
        random_state=random_state,
        class_weight='balanced_subsample',
        min_samples_leaf=2,
    )
    base_model.fit(X_train, y_train)

    try:
        model = CalibratedClassifierCV(base_model, method='isotonic', cv=5)
        model.fit(X_train, y_train)
    except Exception:
        model = base_model

    joblib.dump(model, model_path)
    with open(features_path, 'w') as f:
        f.write('\n'.join(FEATURE_COLUMNS))

    print(f'Saved approval model to {model_path}')
    print(f'Approval dataset saved to {csv_path} ({len(df)} rows)')
    return model


def generate_and_train_default_model(
    n_samples=8000,
    model_path=None,
    features_path=None,
    csv_path=None,
    random_state=42
):
    if model_path is None:
        model_path = os.path.join(MODEL_DIR, 'model.joblib')
    if features_path is None:
        features_path = os.path.join(MODEL_DIR, 'features.txt')
    if csv_path is None:
        csv_path = os.path.join(MODEL_DIR, 'loan_default_data.csv')

    print('Generating realistic loan default data...')
    df = generate_loan_default_dataset(n=n_samples, random_state=random_state)
    df.to_csv(csv_path, index=False)

    X, y = prepare_default_training_data(df)
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, stratify=y, random_state=random_state)

    base_model = RandomForestClassifier(
        n_estimators=150,
        random_state=random_state,
        class_weight='balanced_subsample',
        min_samples_leaf=2,
    )
    base_model.fit(X_train, y_train)

    try:
        model = CalibratedClassifierCV(base_model, method='isotonic', cv=5)
        model.fit(X_train, y_train)
    except Exception:
        model = base_model

    joblib.dump(model, model_path)
    with open(features_path, 'w') as f:
        f.write('\n'.join(DEFAULT_FEATURE_COLUMNS))

    print(f'Saved default model to {model_path}')
    print(f'Default dataset saved to {csv_path} ({len(df)} rows)')
    return model


if __name__ == '__main__':
    generate_and_train_approval_model(n_samples=8000)
    generate_and_train_default_model(n_samples=8000)
