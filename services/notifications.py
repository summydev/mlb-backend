from sqlmodel import Session
from models import Notification, User
from firebase_admin import messaging

def send_collection_notification(db: Session, user_id: int, title: str, body: str, deep_link: str = None):
    """
    Saves an in-app notification and triggers a Firebase Cloud Messaging push notification.
    """
    # 1. Save to database for the in-app notification feed
    new_notif = Notification(
        user_id=user_id,
        title=title,
        body=body,
        deep_link=deep_link
    )
    db.add(new_notif)
    
    # 2. Fetch the target user to get their FCM token
    target_user = db.get(User, user_id)
    
    # 3. Trigger Firebase Push Notification
    if target_user and target_user.fcm_token:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            # Send the deep link as a data payload so Flutter can navigate when tapped
            data={"deep_link": deep_link} if deep_link else {}, 
            token=target_user.fcm_token,
        )
        
        try:
            response = messaging.send(message)
            print(f"✅ Successfully sent push notification: {response}")
        except Exception as e:
            print(f"❌ Error sending push notification: {e}")
    else:
        print(f"⚠️ Push skipped: User {user_id} has no FCM token registered.")

    db.commit()