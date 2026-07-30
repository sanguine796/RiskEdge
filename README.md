# Loan Default Prediction Platform

This project is a prototype Loan Default Prediction web application with a Flask backend, SQL database, and a Scikit-learn model. It includes authentication, a prediction API, explainability outputs, analytics, and an admin panel.

Quick start

1. Create a virtual environment and install requirements:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

2. Train the demo model (saves to `model/model.joblib`):

```bash
python train_model.py
```

3. Copy `.env.example` to `.env` and adjust settings (or set env vars). Then run:

```bash
python app.py
```

4. Open `http://127.0.0.1:5000` in your browser.

Notes
+- By default the app uses SQLite. To switch to MySQL, set `DATABASE_URL` in `.env` to a connection string like:
+  `mysql+mysqlconnector://username:password@localhost:3306/loan_db`
- The admin user can be created by registering with the email set in `ADMIN_EMAIL` in `.env`.
