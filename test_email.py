from flask import Flask
from flask_mail import Mail, Message

app = Flask(__name__)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'ayoomeiza00@gmail.com'        # <-- CHANGE THIS
app.config['MAIL_PASSWORD'] = 'poky emvn jokr dhzs'  # <-- CHANGE THIS
app.config['MAIL_DEFAULT_SENDER'] = 'a@gmail.com'  # <-- CHANGE THIS

mail = Mail(app)

with app.app_context():
    try:
        msg = Message('Test Email', recipients=['your-email@gmail.com'])
        msg.body = 'This is a test email from Flask-Mail! Everything is working correctly.'
        mail.send(msg)
        print('✅ Email sent successfully!')
    except Exception as e:
        print(f'❌ Error: {e}')