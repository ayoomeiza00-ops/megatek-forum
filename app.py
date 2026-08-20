from flask import Flask, render_template, redirect, url_for, flash, request, jsonify, session, make_response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, TextAreaField, SubmitField, SelectField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError, Email
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta
import markdown
from markupsafe import Markup
import os
import secrets
import random
from validate_email import validate_email
from flask_mail import Mail, Message
from flask_ckeditor import CKEditor, CKEditorField


app = Flask(__name__)

# ========== ENSURE INSTANCE FOLDER EXISTS (FIX FOR RENDER) ==========
instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
if not os.path.exists(instance_path):
    os.makedirs(instance_path)
    print(f"✅ Created instance folder at: {instance_path}")

# ========== SECURITY ==========
app.config['SECRET_KEY'] = 'ca94d08efa47d184f635d69c0cdd9191fcd522c86ad4ea053684b60bff752165'

# ========== DATABASE ==========
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/forum.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False


# ========== EMAIL ==========
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'ayoomeiza00@gmail.com'
app.config['MAIL_PASSWORD'] = 'poky emvn jokr dhzs'
app.config['MAIL_DEFAULT_SENDER'] = 'ayoomeiza00@gmail.com'

mail = Mail(app)
ckeditor = CKEditor(app)

# ========== SESSION ==========
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400

# ========== UPLOADS ==========
UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ========== CONTEXT ==========
@app.context_processor
def inject_unread():
    if current_user.is_authenticated:
        unread_notifications = current_user.unread_count()
        unread_messages = PrivateMessage.query.filter_by(receiver_id=current_user.id, read=False).count()
        return {
            'unread_count': unread_notifications,
            'unread_messages': unread_messages
        }
    return {'unread_count': 0, 'unread_messages': 0}

# ========== MARKDOWN ==========
@app.template_filter('markdown')
def markdown_filter(text):
    if text:
        return Markup(markdown.markdown(text, extensions=['fenced_code', 'tables', 'nl2br']))
    return ''

# ========== DATABASE ==========
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ========== MODELS ==========

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    avatar = db.Column(db.String(200), nullable=True)
    is_admin = db.Column(db.Boolean, default=False)
    joined_date = db.Column(db.DateTime, default=datetime.utcnow)
    reputation = db.Column(db.Integer, default=0)
    dark_mode = db.Column(db.Boolean, default=False)
    
    email_verified = db.Column(db.Boolean, default=False)
    verification_code = db.Column(db.String(10), nullable=True)
    code_expiry = db.Column(db.DateTime, nullable=True)
    
    reset_token = db.Column(db.String(100), nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)
    
    last_active = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    
    following = db.relationship('Follow', foreign_keys='Follow.follower_id', backref='follower', lazy=True)
    followers = db.relationship('Follow', foreign_keys='Follow.followed_id', backref='followed', lazy=True)
    drafts = db.relationship('Draft', backref='author', lazy=True)
    posts = db.relationship('Post', backref='author', lazy=True)
    comments = db.relationship('Comment', backref='author', lazy=True)
    upvotes = db.relationship('Upvote', backref='user', lazy=True)
    notifications = db.relationship('Notification', foreign_keys='Notification.user_id', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def post_count(self):
        return Post.query.filter_by(user_id=self.id).count()

    def comment_count(self):
        return Comment.query.filter_by(user_id=self.id).count()

    def unread_count(self):
        return Notification.query.filter_by(user_id=self.id, read=False).count()

    def generate_verification_code(self):
        self.verification_code = str(random.randint(100000, 999999))
        self.code_expiry = datetime.utcnow() + timedelta(minutes=10)
        return self.verification_code

    def is_verification_code_valid(self, code):
        if not self.verification_code or not self.code_expiry:
            return False
        if self.verification_code != code:
            return False
        if datetime.utcnow() > self.code_expiry:
            return False
        return True

    def generate_reset_token(self):
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    def is_reset_token_valid(self, token):
        if not self.reset_token or not self.reset_token_expiry:
            return False
        if self.reset_token != token:
            return False
        if datetime.utcnow() > self.reset_token_expiry:
            return False
        return True

class Follow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    followed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('follower_id', 'followed_id', name='unique_follow'),)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=True)
    icon = db.Column(db.String(50), nullable=True)
    posts = db.relationship('Post', backref='category', lazy=True)

class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    posts = db.relationship('PostTag', backref='tag', lazy=True)

class Draft(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=True)
    content = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    tags = db.Column(db.String(200), nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    image = db.Column(db.String(200), nullable=True)
    category = db.relationship('Category', backref='drafts')

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    views = db.Column(db.Integer, default=0)
    image = db.Column(db.String(200), nullable=True)
    is_trending = db.Column(db.Boolean, default=False)
    comments = db.relationship('Comment', backref='post', lazy=True, cascade="all, delete-orphan")
    tags = db.relationship('PostTag', backref='post', lazy=True, cascade="all, delete-orphan")
    upvotes = db.relationship('Upvote', backref='post', lazy=True, cascade="all, delete-orphan")

    def comment_count(self):
        return Comment.query.filter_by(post_id=self.id).count()

    def upvote_count(self):
        return Upvote.query.filter_by(post_id=self.id).count()

class PostTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey('tag.id'), nullable=False)

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    image = db.Column(db.String(200), nullable=True)
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy=True)
    upvotes = db.relationship('CommentUpvote', backref='comment', lazy=True, cascade="all, delete-orphan")

    def upvote_count(self):
        return CommentUpvote.query.filter_by(comment_id=self.id).count()

class Upvote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)

class CommentUpvote(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=False)

class PrivateMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    read = db.Column(db.Boolean, default=False)
    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    action = db.Column(db.String(50), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User', backref='activities')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comment.id'), nullable=True)
    type = db.Column(db.String(50), nullable=False)
    message = db.Column(db.String(200), nullable=False)
    read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', foreign_keys=[user_id])
    sender = db.relationship('User', foreign_keys=[sender_id])
    post = db.relationship('Post', foreign_keys=[post_id])
    comment = db.relationship('Comment', foreign_keys=[comment_id])

# ========== FORMS ==========

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('Username already taken.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email already registered.')
        try:
            is_valid = validate_email(email.data, verify=True)
            if not is_valid:
                raise ValidationError('Please enter a valid email address (no temporary/disposable emails).')
        except:
            if '@' not in email.data or '.' not in email.data.split('@')[-1]:
                raise ValidationError('Please enter a valid email address.')

class VerificationForm(FlaskForm):
    code = StringField('Verification Code', validators=[DataRequired(), Length(min=6, max=6)])
    submit = SubmitField('Verify Email')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

class PostForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    content = CKEditorField('Content', validators=[DataRequired()])
    category_id = SelectField('Category', coerce=int, validators=[DataRequired()])
    tags = StringField('Tags (comma separated)')
    submit = SubmitField('Publish Post')

class CommentForm(FlaskForm):
    content = CKEditorField('Add Comment', validators=[DataRequired()])
    parent_id = SelectField('Reply to', coerce=int, choices=[], validators=[])
    submit = SubmitField('Post Comment')

class ProfileForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=2, max=20)])
    email = StringField('Email', validators=[Email(), Length(max=120)])
    bio = TextAreaField('Bio')
    dark_mode = BooleanField('Dark Mode')
    submit = SubmitField('Update Profile')

class PrivateMessageForm(FlaskForm):
    receiver = StringField('To', validators=[DataRequired()])
    content = TextAreaField('Message', validators=[DataRequired()])
    submit = SubmitField('Send')

class ResetPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Send Reset Link')

class ResetPasswordConfirmForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')

class DraftForm(FlaskForm):
    title = StringField('Title', validators=[Length(max=200)])
    content = CKEditorField('Content')
    category_id = SelectField('Category', coerce=int, choices=[])
    tags = StringField('Tags (comma separated)')
    submit = SubmitField('Save Draft')

# ========== EMAIL HELPERS ==========

def send_verification_email(user):
    code = user.generate_verification_code()
    db.session.commit()
    msg = Message(
        subject='Verify Your Email - Megatek ICT Academy',
        recipients=[user.email],
        body=f"""
Hello {user.username},

Thank you for registering at Megatek ICT Academy Forum.

Please enter the following 6-digit verification code to activate your account:

🔑 {code}

This code is valid for 10 minutes.

If you did not create an account, please ignore this email.

Best regards,
Megatek ICT Academy Team
        """
    )
    try:
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

def send_reset_email(user):
    token = user.generate_reset_token()
    db.session.commit()
    reset_url = url_for('reset_password_confirm', token=token, _external=True)
    msg = Message(
        subject='Password Reset - Megatek ICT Academy',
        recipients=[user.email],
        body=f"""
Hello {user.username},

You requested to reset your password for your Megatek ICT Academy Forum account.

Click the link below to reset your password:

🔗 {reset_url}

This link is valid for 1 hour.

If you did not request this, please ignore this email.

Best regards,
Megatek ICT Academy Team
        """
    )
    try:
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email sending failed: {e}")
        return False

# ========== SETUP ROUTE (ONE-TIME USE) ==========
@app.route('/setup')
def setup():
    with app.app_context():
        db.create_all()
        seed_categories()
        seed_tags()
        
        # Check if admin exists
        admin = User.query.filter_by(username='Olodo uprising').first()
        if not admin:
            admin = User(username='Olodo uprising', email='ayoomeiza00@gmail.com')
            admin.set_password('12345678')
            admin.is_admin = True
            admin.email_verified = True
            db.session.add(admin)
            db.session.commit()
            return """
            <h2>✅ Setup Complete!</h2>
            <p><strong>Admin account created:</strong></p>
            <ul>
                <li><strong>Username:</strong> Olodo uprising</li>
                <li><strong>Password:</strong> 12345678</li>
            </ul>
            <p><a href="/login">Click here to login</a></p>
            <p style="color:red;font-size:12px;"><strong>IMPORTANT:</strong> After logging in, go to Profile → Edit Profile and change your password!</p>
            """
        else:
            return """
            <h2>⚠️ Setup Already Run</h2>
            <p>Admin account already exists.</p>
            <p><a href="/login">Click here to login</a></p>
            """
# ========== ROUTES ==========

@app.route('/')
def index():
    page = request.args.get('page', 1, type=int)
    per_page = 10
    posts = Post.query.order_by(Post.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    categories = Category.query.all()
    users = User.query.all()
    tags = Tag.query.all()
    recent_activity = Activity.query.order_by(Activity.timestamp.desc()).limit(10).all()
    
    if current_user.is_authenticated:
        current_user.last_active = datetime.utcnow()
        current_user.is_online = True
        db.session.commit()
    
    timeout = datetime.utcnow() - timedelta(minutes=5)
    offline_users = User.query.filter(User.last_active < timeout, User.is_online == True).all()
    for user in offline_users:
        user.is_online = False
    db.session.commit()
    
    return render_template('index.html', posts=posts, categories=categories, users=users, tags=tags, recent_activity=recent_activity)

@app.route('/users')
def users():
    all_users = User.query.order_by(User.joined_date.desc()).all()
    return render_template('users.html', users=all_users)

@app.route('/tags')
def tags():
    all_tags = Tag.query.order_by(Tag.name).all()
    return render_template('tags.html', tags=all_tags)

@app.route('/popular')
def popular():
    posts = Post.query.order_by(Post.views.desc()).limit(20).all()
    return render_template('popular.html', posts=posts)

@app.route('/trending')
def trending():
    cutoff = datetime.utcnow() - timedelta(hours=24)
    posts = Post.query.filter(Post.timestamp > cutoff).all()
    posts.sort(key=lambda p: p.views + p.upvote_count() * 2, reverse=True)
    posts = posts[:20]
    return render_template('trending.html', posts=posts)

@app.route('/following')
@login_required
def following_feed():
    followed_ids = [f.followed_id for f in current_user.following]
    posts = Post.query.filter(Post.user_id.in_(followed_ids)).order_by(Post.timestamp.desc()).all()
    return render_template('following.html', posts=posts)

@app.route('/follow/<int:user_id>', methods=['POST'])
@login_required
def follow_user(user_id):
    if user_id == current_user.id:
        flash('You cannot follow yourself.', 'danger')
        return redirect(url_for('profile', user_id=user_id))
    
    user = User.query.get_or_404(user_id)
    existing = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first()
    
    if existing:
        db.session.delete(existing)
        flash(f'Unfollowed {user.username}.', 'info')
    else:
        follow = Follow(follower_id=current_user.id, followed_id=user_id)
        db.session.add(follow)
        flash(f'Now following {user.username}!', 'success')
    
    db.session.commit()
    return redirect(url_for('profile', user_id=user_id))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        if send_verification_email(user):
            flash('A verification code has been sent to your email.', 'info')
            return redirect(url_for('verify_email', user_id=user.id))
        else:
            flash('Could not send verification email.', 'danger')
            return redirect(url_for('login'))
    return render_template('register.html', form=form)

@app.route('/verify/<int:user_id>', methods=['GET', 'POST'])
def verify_email(user_id):
    user = User.query.get_or_404(user_id)
    if user.email_verified:
        flash('Your email is already verified.', 'info')
        return redirect(url_for('login'))
    
    form = VerificationForm()
    if form.validate_on_submit():
        if user.is_verification_code_valid(form.code.data):
            user.email_verified = True
            user.verification_code = None
            user.code_expiry = None
            db.session.commit()
            flash('Email verified successfully!', 'success')
            return redirect(url_for('login'))
        else:
            flash('Invalid or expired verification code.', 'danger')
    
    return render_template('verify.html', form=form, user=user)

@app.route('/resend_code/<int:user_id>')
def resend_code(user_id):
    user = User.query.get_or_404(user_id)
    if user.email_verified:
        flash('Your email is already verified.', 'info')
        return redirect(url_for('login'))
    if send_verification_email(user):
        flash('A new verification code has been sent to your email.', 'success')
    else:
        flash('Failed to send email.', 'danger')
    return redirect(url_for('verify_email', user_id=user.id))

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            if send_reset_email(user):
                flash('Password reset link has been sent to your email.', 'info')
            else:
                flash('Failed to send email.', 'danger')
        else:
            flash('No account found with that email address.', 'danger')
        return redirect(url_for('login'))
    return render_template('forgot_password.html', form=form)

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_confirm(token):
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.is_reset_token_valid(token):
        flash('Invalid or expired reset link.', 'danger')
        return redirect(url_for('forgot_password'))
    
    form = ResetPasswordConfirmForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        flash('Password reset successfully!', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html', form=form)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            if not user.email_verified:
                flash('Please verify your email before logging in.', 'warning')
                return redirect(url_for('verify_email', user_id=user.id))
            user.is_online = True
            user.last_active = datetime.utcnow()
            db.session.commit()
            login_user(user)
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('index'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html', form=form)

@app.route('/logout')
@login_required
def logout():
    current_user.is_online = False
    db.session.commit()
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

@app.route('/search', methods=['GET', 'POST'])
def search():
    query = request.args.get('q', '')
    if query:
        posts = Post.query.filter(Post.title.contains(query) | Post.content.contains(query)).all()
    else:
        posts = []
    return render_template('search.html', posts=posts, query=query)

@app.route('/api/unread_count')
@login_required
def api_unread_count():
    return jsonify({'unread_count': current_user.unread_count()})

@app.route('/api/check_notifications')
@login_required
def api_check_notifications():
    notifications = Notification.query.filter_by(user_id=current_user.id, read=False).order_by(Notification.timestamp.desc()).limit(5).all()
    notif_list = [{'id': n.id, 'message': n.message, 'post_id': n.post_id, 'timestamp': n.timestamp.strftime('%b %d, %H:%M')} for n in notifications]
    return jsonify({'unread_count': current_user.unread_count(), 'notifications': notif_list})

@app.route('/drafts')
@login_required
def drafts():
    user_drafts = Draft.query.filter_by(user_id=current_user.id).order_by(Draft.updated_at.desc()).all()
    return render_template('drafts.html', drafts=user_drafts)

@app.route('/draft/new', methods=['GET', 'POST'])
@login_required
def new_draft():
    form = DraftForm()
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.all()]
    
    if form.validate_on_submit():
        draft = Draft(
            title=form.title.data,
            content=form.content.data,
            category_id=form.category_id.data if form.category_id.data != 0 else None,
            tags=form.tags.data,
            author=current_user
        )
        db.session.add(draft)
        db.session.commit()
        flash('Draft saved!', 'success')
        return redirect(url_for('drafts'))
    
    return render_template('create_draft.html', form=form)

@app.route('/draft/<int:draft_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_draft(draft_id):
    draft = Draft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        flash('You can only edit your own drafts.', 'danger')
        return redirect(url_for('index'))
    
    form = DraftForm()
    form.category_id.choices = [(0, 'No Category')] + [(c.id, c.name) for c in Category.query.all()]
    
    if form.validate_on_submit():
        draft.title = form.title.data
        draft.content = form.content.data
        draft.category_id = form.category_id.data if form.category_id.data != 0 else None
        draft.tags = form.tags.data
        draft.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Draft updated!', 'success')
        return redirect(url_for('drafts'))
    
    form.title.data = draft.title
    form.content.data = draft.content
    form.category_id.data = draft.category_id or 0
    form.tags.data = draft.tags
    return render_template('edit_draft.html', form=form, draft=draft)

@app.route('/draft/<int:draft_id>/delete', methods=['POST'])
@login_required
def delete_draft(draft_id):
    draft = Draft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        flash('You can only delete your own drafts.', 'danger')
        return redirect(url_for('index'))
    db.session.delete(draft)
    db.session.commit()
    flash('Draft deleted.', 'info')
    return redirect(url_for('drafts'))

@app.route('/draft/<int:draft_id>/publish', methods=['GET', 'POST'])
@login_required
def publish_draft(draft_id):
    draft = Draft.query.get_or_404(draft_id)
    if draft.user_id != current_user.id:
        flash('You can only publish your own drafts.', 'danger')
        return redirect(url_for('index'))
    
    form = PostForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    
    if form.validate_on_submit():
        post = Post(
            title=form.title.data or draft.title,
            content=form.content.data or draft.content,
            author=current_user,
            category_id=form.category_id.data
        )
        db.session.add(post)
        db.session.flush()
        
        if draft.image and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], draft.image)):
            import shutil
            new_filename = f"post_{post.id}_{draft.image}"
            shutil.copy(os.path.join(app.config['UPLOAD_FOLDER'], draft.image), os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
            post.image = new_filename
        
        if form.tags.data:
            for name in [t.strip().lower() for t in form.tags.data.split(',') if t.strip()]:
                tag = Tag.query.filter_by(name=name).first() or Tag(name=name)
                if not tag.id:
                    db.session.add(tag)
                    db.session.flush()
                db.session.add(PostTag(post_id=post.id, tag_id=tag.id))
        
        db.session.delete(draft)
        db.session.commit()
        
        db.session.add(Activity(user_id=current_user.id, action='published a post', target_type='post', target_id=post.id))
        db.session.commit()
        
        flash('Post published from draft!', 'success')
        return redirect(url_for('view_post', post_id=post.id))
    
    form.title.data = draft.title
    form.content.data = draft.content
    form.category_id.data = draft.category_id or Category.query.first().id if Category.query.first() else None
    form.tags.data = draft.tags
    return render_template('publish_draft.html', form=form, draft=draft)

@app.route('/post/new', methods=['GET', 'POST'])
@login_required
def new_post():
    if not current_user.email_verified:
        flash('You must verify your email before creating a post.', 'warning')
        return redirect(url_for('verify_email', user_id=current_user.id))
    
    form = PostForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        post = Post(title=form.title.data, content=form.content.data, author=current_user, category_id=form.category_id.data)
        db.session.add(post)
        db.session.flush()
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                post.image = filename
        if form.tags.data:
            for name in [t.strip().lower() for t in form.tags.data.split(',') if t.strip()]:
                tag = Tag.query.filter_by(name=name).first() or Tag(name=name)
                if not tag.id:
                    db.session.add(tag)
                    db.session.flush()
                db.session.add(PostTag(post_id=post.id, tag_id=tag.id))
        db.session.commit()
        db.session.add(Activity(user_id=current_user.id, action='created a post', target_type='post', target_id=post.id))
        db.session.commit()
        flash('Post published!', 'success')
        return redirect(url_for('index'))
    return render_template('create_post.html', form=form)

@app.route('/post/<int:post_id>', methods=['GET', 'POST'])
def view_post(post_id):
    post = Post.query.get_or_404(post_id)
    form = CommentForm()
    form.parent_id.choices = [(0, 'Reply to Post')] + [(c.id, f'Reply to {c.author.username}') for c in post.comments if c.parent_id is None]
    
    viewed_posts = request.cookies.get('viewed_posts', '')
    viewed_list = viewed_posts.split(',') if viewed_posts else []
    
    if str(post_id) not in viewed_list:
        post.views += 1
        viewed_list.append(str(post_id))
        db.session.commit()

    if form.validate_on_submit() and current_user.is_authenticated:
        if not current_user.email_verified:
            flash('You must verify your email before commenting.', 'warning')
            return redirect(url_for('verify_email', user_id=current_user.id))
        
        parent_id = form.parent_id.data if form.parent_id.data != 0 else None
        comment = Comment(content=form.content.data, post=post, author=current_user, parent_id=parent_id)
        db.session.add(comment)
        db.session.flush()
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                comment.image = filename
        db.session.commit()
        if comment.author.id != post.author.id:
            notif = Notification(user_id=post.author.id, sender_id=comment.author.id, post_id=post.id, comment_id=comment.id, type='comment', message=f'{comment.author.username} commented on your post: "{post.title}"')
            db.session.add(notif)
            db.session.commit()
        db.session.add(Activity(user_id=current_user.id, action='commented on a post', target_type='post', target_id=post.id))
        db.session.commit()
        flash('Comment added!', 'success')
        return redirect(url_for('view_post', post_id=post.id))
    
    comments = Comment.query.filter_by(post_id=post.id, parent_id=None).order_by(Comment.timestamp.asc()).all()
    response = make_response(render_template('view_post.html', post=post, comments=comments, form=form))
    response.set_cookie('viewed_posts', ','.join(viewed_list), max_age=60*60*24*30)
    return response

@app.route('/post/<int:post_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user and not current_user.is_admin:
        flash('You can only edit your own posts.', 'danger')
        return redirect(url_for('index'))
    form = PostForm()
    form.category_id.choices = [(c.id, c.name) for c in Category.query.all()]
    if form.validate_on_submit():
        post.title = form.title.data
        post.content = form.content.data
        post.category_id = form.category_id.data
        post.updated_at = datetime.utcnow()
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                if post.image and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], post.image)):
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], post.image))
                filename = secure_filename(f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                post.image = filename
        PostTag.query.filter_by(post_id=post.id).delete()
        if form.tags.data:
            for name in [t.strip().lower() for t in form.tags.data.split(',') if t.strip()]:
                tag = Tag.query.filter_by(name=name).first() or Tag(name=name)
                if not tag.id:
                    db.session.add(tag)
                    db.session.flush()
                db.session.add(PostTag(post_id=post.id, tag_id=tag.id))
        db.session.commit()
        flash('Post updated!', 'success')
        return redirect(url_for('view_post', post_id=post.id))
    form.title.data = post.title
    form.content.data = post.content
    form.category_id.data = post.category_id
    if post.tags:
        form.tags.data = ', '.join([t.tag.name for t in post.tags])
    return render_template('edit_post.html', form=form, post=post)

@app.route('/post/<int:post_id>/delete', methods=['POST'])
@login_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    if post.author != current_user and not current_user.is_admin:
        flash('You can only delete your own posts.', 'danger')
        return redirect(url_for('index'))
    if post.image and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], post.image)):
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], post.image))
    db.session.delete(post)
    db.session.commit()
    flash('Post deleted.', 'info')
    return redirect(url_for('index'))

@app.route('/post/<int:post_id>/upvote_ajax', methods=['POST'])
@login_required
def upvote_post_ajax(post_id):
    post = Post.query.get_or_404(post_id)
    existing = Upvote.query.filter_by(user_id=current_user.id, post_id=post.id).first()
    if existing:
        db.session.delete(existing)
        post.author.reputation -= 1
    else:
        db.session.add(Upvote(user_id=current_user.id, post_id=post.id))
        post.author.reputation += 1
        if post.author.id != current_user.id:
            notif = Notification(user_id=post.author.id, sender_id=current_user.id, post_id=post.id, type='like', message=f'{current_user.username} liked your post: "{post.title}"')
            db.session.add(notif)
    db.session.commit()
    return jsonify({'success': True, 'count': post.upvote_count()})

@app.route('/comment/<int:comment_id>/upvote_ajax', methods=['POST'])
@login_required
def upvote_comment_ajax(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    existing = CommentUpvote.query.filter_by(user_id=current_user.id, comment_id=comment.id).first()
    if existing:
        db.session.delete(existing)
    else:
        db.session.add(CommentUpvote(user_id=current_user.id, comment_id=comment.id))
    db.session.commit()
    return jsonify({'success': True, 'count': comment.upvote_count()})

@app.route('/comment/<int:comment_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.author != current_user and not current_user.is_admin:
        flash('You can only edit your own comments.', 'danger')
        return redirect(url_for('view_post', post_id=comment.post_id))
    if request.method == 'POST':
        comment.content = request.form.get('content')
        comment.updated_at = datetime.utcnow()
        db.session.commit()
        flash('Comment updated!', 'success')
        return redirect(url_for('view_post', post_id=comment.post_id))
    return render_template('edit_comment.html', comment=comment)

@app.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    if comment.author != current_user and not current_user.is_admin:
        flash('You can only delete your own comments.', 'danger')
        return redirect(url_for('view_post', post_id=comment.post_id))
    if comment.image and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], comment.image)):
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], comment.image))
    post_id = comment.post_id
    db.session.delete(comment)
    db.session.commit()
    flash('Comment deleted.', 'info')
    return redirect(url_for('view_post', post_id=post_id))

@app.route('/profile/<int:user_id>')
def profile(user_id):
    user = User.query.get_or_404(user_id)
    posts = Post.query.filter_by(user_id=user.id).order_by(Post.timestamp.desc()).all()
    is_following = False
    if current_user.is_authenticated:
        is_following = Follow.query.filter_by(follower_id=current_user.id, followed_id=user_id).first() is not None
    return render_template('profile.html', user=user, posts=posts, is_following=is_following)

@app.route('/profile/edit', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = ProfileForm()
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.email = form.email.data
        current_user.bio = form.bio.data
        current_user.dark_mode = form.dark_mode.data
        if 'avatar' in request.files:
            file = request.files['avatar']
            if file and file.filename and allowed_file(file.filename):
                if current_user.avatar and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar)):
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], current_user.avatar))
                filename = secure_filename(f"avatar_{current_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                current_user.avatar = filename
        db.session.commit()
        flash('Profile updated!', 'success')
        return redirect(url_for('profile', user_id=current_user.id))
    form.username.data = current_user.username
    form.email.data = current_user.email
    form.bio.data = current_user.bio
    form.dark_mode.data = current_user.dark_mode
    return render_template('edit_profile.html', form=form)

@app.route('/category/<int:category_id>')
def category_posts(category_id):
    category = Category.query.get_or_404(category_id)
    page = request.args.get('page', 1, type=int)
    per_page = 10
    posts = Post.query.filter_by(category_id=category.id).order_by(Post.timestamp.desc()).paginate(page=page, per_page=per_page, error_out=False)
    return render_template('category.html', category=category, posts=posts)

@app.route('/tag/<string:tag_name>')
def tag_posts(tag_name):
    tag = Tag.query.filter_by(name=tag_name.lower()).first_or_404()
    posts = Post.query.join(PostTag).join(Tag).filter(Tag.name == tag_name.lower()).order_by(Post.timestamp.desc()).all()
    return render_template('tag.html', tag=tag, posts=posts)

@app.route('/messages')
@login_required
def messages():
    received = PrivateMessage.query.filter_by(receiver_id=current_user.id).order_by(PrivateMessage.timestamp.desc()).all()
    sent = PrivateMessage.query.filter_by(sender_id=current_user.id).order_by(PrivateMessage.timestamp.desc()).all()
    return render_template('messages.html', received=received, sent=sent)

@app.route('/messages/send', methods=['GET', 'POST'])
@login_required
def send_message():
    form = PrivateMessageForm()
    if form.validate_on_submit():
        receiver = User.query.filter_by(username=form.receiver.data).first()
        if not receiver:
            flash('User not found.', 'danger')
            return redirect(url_for('send_message'))
        db.session.add(PrivateMessage(sender_id=current_user.id, receiver_id=receiver.id, content=form.content.data))
        db.session.commit()
        flash('Message sent!', 'success')
        return redirect(url_for('messages'))
    return render_template('send_message.html', form=form)

@app.route('/messages/<int:message_id>/read')
@login_required
def read_message(message_id):
    msg = PrivateMessage.query.get_or_404(message_id)
    if msg.receiver_id != current_user.id:
        flash('You do not have permission.', 'danger')
        return redirect(url_for('messages'))
    msg.read = True
    db.session.commit()
    return render_template('read_message.html', message=msg)

@app.route('/notifications')
@login_required
def notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.timestamp.desc()).all()
    for n in notifs:
        n.read = True
    db.session.commit()
    return render_template('notifications.html', notifications=notifs)

@app.route('/toggle_dark_mode', methods=['POST'])
@login_required
def toggle_dark_mode():
    current_user.dark_mode = not current_user.dark_mode
    db.session.commit()
    flash(f'Dark mode {"enabled" if current_user.dark_mode else "disabled"}', 'info')
    return redirect(request.referrer or url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('index'))
    users = User.query.all()
    posts = Post.query.all()
    comments = Comment.query.all()
    return render_template('admin.html', users=users, posts=posts, comments=comments)

@app.route('/admin/delete_user/<int:user_id>', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('index'))
    
    user = User.query.get_or_404(user_id)
    
    if user.is_admin:
        flash('Cannot delete another admin.', 'danger')
        return redirect(url_for('admin_dashboard'))
    
    try:
        Follow.query.filter_by(follower_id=user.id).delete()
        Follow.query.filter_by(followed_id=user.id).delete()
        Notification.query.filter_by(user_id=user.id).delete()
        Notification.query.filter_by(sender_id=user.id).delete()
        Upvote.query.filter_by(user_id=user.id).delete()
        CommentUpvote.query.filter_by(user_id=user.id).delete()
        PrivateMessage.query.filter_by(sender_id=user.id).delete()
        PrivateMessage.query.filter_by(receiver_id=user.id).delete()
        Activity.query.filter_by(user_id=user.id).delete()
        Draft.query.filter_by(user_id=user.id).delete()
        db.session.delete(user)
        db.session.commit()
        flash(f'User {user.username} deleted successfully.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error deleting user: {str(e)}', 'danger')
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/make_admin/<int:user_id>', methods=['POST'])
@login_required
def admin_make_admin(user_id):
    if not current_user.is_admin:
        flash('Admin access required.', 'danger')
        return redirect(url_for('index'))
    user = User.query.get_or_404(user_id)
    user.is_admin = True
    db.session.commit()
    flash(f'{user.username} is now an admin.', 'success')
    return redirect(url_for('admin_dashboard'))

# ========== SEED DATA ==========

def seed_categories():
    cats = [
        ('Python', 'Discuss Python programming', 'fa-python'),
        ('JavaScript', 'JavaScript & frameworks', 'fa-js'),
        ('Web Development', 'HTML, CSS, web frameworks', 'fa-globe'),
        ('Data Science', 'Data, ML, AI', 'fa-database'),
        ('Career Advice', 'Jobs, resumes, interviews', 'fa-briefcase'),
        ('General Discussion', 'Tech talk', 'fa-comments'),
        ('Flask & Django', 'Python web frameworks', 'fa-flask'),
        ('React & Vue', 'Frontend JS frameworks', 'fa-react'),
        ('DevOps', 'CI/CD, Docker, cloud', 'fa-cloud'),
        ('Cyber Security', 'Security, hacking', 'fa-shield-alt'),
        ('Machine Learning', 'ML, AI, deep learning', 'fa-robot'),
        ('Mobile Development', 'iOS, Android', 'fa-mobile-alt'),
        ('Cloud Computing', 'AWS, Azure, GCP', 'fa-cloud-upload-alt'),
        ('Blockchain', 'Crypto, Web3', 'fa-link'),
        ('Game Development', 'Unity, Unreal', 'fa-gamepad'),
        ('UI/UX Design', 'Design, Figma', 'fa-paint-brush'),
        ('Open Source', 'Open source contributions', 'fa-code-branch'),
        ('Tech News', 'Latest tech news', 'fa-newspaper')
    ]
    for name, desc, icon in cats:
        if not Category.query.filter_by(name=name).first():
            db.session.add(Category(name=name, description=desc, icon=icon))
    db.session.commit()

def seed_tags():
    tags = ['python','flask','django','javascript','react','vue','html','css','sql','ml','ai','career','devops','security','cloud','blockchain','gamedev','uxui']
    for name in tags:
        if not Tag.query.filter_by(name=name).first():
            db.session.add(Tag(name=name))
    db.session.commit()

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        seed_categories()
        seed_tags()
    app.run(debug=True)