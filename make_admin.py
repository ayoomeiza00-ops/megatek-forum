from app import app, db, User

with app.app_context():
    user = User.query.filter_by(username='Olodo uprising').first()
    if user:
        user.is_admin = True
        db.session.commit()
        print(f'✅ {user.username} is now an admin!')
    else:
        print('❌ User not found')