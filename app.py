from flask import Flask, request, render_template, redirect, flash, jsonify, session, url_for
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import base64
import re

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# DB config
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'abcd6658'
app.config['MYSQL_DB'] = 'twitter_clone'
mysql = MySQL(app)

def get_unread_notification_count(user_id):
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT COUNT(*) 
            FROM notifications 
            WHERE user_id = %s AND is_read = FALSE
        """, (user_id,))
        count = cur.fetchone()[0]
        cur.close()
        return count
    except Exception as e:
        print(f"Error fetching unread notification count: {str(e)}")
        return 0

@app.route('/')
def index():
    if is_logged_in():
        return redirect(url_for('home'))
    
    return render_template('index.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        try:
            name = request.form['name']
            dob = request.form['dob']
            email = request.form['email']
            password = request.form['password']

            # Hash the password
            password_hash = generate_password_hash(password)

            cur = mysql.connection.cursor()

            # Prepare input args + dummy OUT param
            args = [name, dob, email, password_hash, 0]

            # Call the stored procedure
            cur.callproc('register_user', args)

            # Fetch all result sets (likely none, but good to do)
            try:
                while True:
                    result_set = cur.fetchall()
                    print("Procedure returned result set:", result_set)
                    if not cur.nextset():
                        break
            except Exception as e:
                print("No more result sets or error while fetching:", e)

            # Commit the transaction
            mysql.connection.commit()

            # Fetch the OUT parameter explicitly from the session variable
            cur.execute("SELECT @_register_user_4")  # 4 = index of OUT param in callproc args
            user_id = cur.fetchone()[0]
            print("User ID from OUT parameter session variable:", user_id)

            cur.close()

            if user_id:
                session['user_id'] = user_id
                print("User registered successfully and logged in! user_id =", user_id)
                return redirect(url_for('home'))
            else:
                print("Registration failed: OUT parameter user_id is 0 or None")
                return redirect(url_for('signup'))

        except mysql.connection.Error as err:
            # Handle duplicate email error from SIGNAL in procedure
            if err.args[0] == 1644:  # MySQL SIGNAL error code for user-defined exception
                print("Email already registered error:", err.args[1])
                return render_template('/signup1.html', error="Email already registered")
            else:
                print("Database error during signup:", err)
                return redirect(url_for('signup'))
        except Exception as e:
            print("Exception during signup:", e)
            return redirect(url_for('signup'))

    return render_template('/signup1.html')

@app.route('/check-identifier', methods=['POST'])
def check_identifier():
    data = request.json
    identifier = data.get('identifier')

    if not identifier:
        return jsonify({"error": "Identifier is required"}), 400

    cursor = mysql.connection.cursor()
    query = """
        SELECT 1 FROM users
        WHERE (phone = %s OR email = %s OR username = %s) AND isActive = 1
        LIMIT 1;
    """
    cursor.execute(query, (identifier, identifier, identifier))
    result = cursor.fetchone()
    cursor.close()

    if result:
        return jsonify({"message": "User already exists", "exists": True})
    else:
        return jsonify({"message": "User not found.", "exists": False})

@app.route('/signin1', methods=['GET', 'POST'])
def singIn1():
    if is_logged_in():
        return redirect(url_for('home'))
    return render_template('signin1.html')

@app.route('/signin2', methods=['GET', 'POST'])
def singIn2():
    if is_logged_in():
        return redirect(url_for('home'))
    if request.method == 'POST':
        data = request.get_json()
        identifier = data.get('identifier')
        return render_template('signin2.html', identifier=identifier)
    
    return render_template('signin2.html', identifier=None)

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Invalid JSON input"}), 400

    identifier = data.get('identifier')
    password = data.get('password')

    if not identifier or not password:
        return jsonify({"success": False, "message": "Identifier and password are required"}), 400

    try:
        cur = mysql.connection.cursor()
        query = """
            SELECT id, name, username, password_hash
            FROM users 
            WHERE username = %s OR email = %s OR phone = %s
            LIMIT 1;
        """
        cur.execute(query, (identifier, identifier, identifier))
        user = cur.fetchone()
        cur.close()

        if user:
            user_id, name, username, stored_password_hash = user

            if check_password_hash(stored_password_hash, password):
                session['user_id'] = user_id
                session['username'] = username
                return jsonify({"success": True, "message": "Login successful"})
            else:
                return jsonify({"success": False, "message": "Incorrect password"}), 401
        else:
            return jsonify({"success": False, "message": "User not found"}), 404

    except Exception as e:
        return jsonify({"success": False, "message": f"An error occurred: {str(e)}"}), 500

@app.route('/home')
def home():
    user_id = session.get('user_id')
    if not user_id:
        flash("Please sign in to view your home feed.", "warning")
        return redirect(url_for('index'))

    try:
        cur = mysql.connection.cursor()
        # Fetch user details
        cur.execute("SELECT name, username, email, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()

        # Fetch tweets with user info, counts, and user interaction states
        # cur.execute("""
        #     SELECT 
        #         t.id, t.content, t.created_at, u.name, u.username, u.profile_pic_base64,
        #         (SELECT COUNT(*) FROM likes l WHERE l.tweet_id = t.id) AS like_count,
        #         (SELECT COUNT(*) FROM retweets r WHERE r.tweet_id = t.id) AS retweet_count,
        #         (SELECT COUNT(*) FROM comments c WHERE c.tweet_id = t.id) AS comment_count,
        #         (SELECT 1 FROM likes l WHERE l.tweet_id = t.id AND l.user_id = %s LIMIT 1) AS user_liked,
        #         (SELECT 1 FROM retweets r WHERE r.tweet_id = t.id AND r.user_id = %s LIMIT 1) AS user_retweeted
        #     FROM tweets t
        #     JOIN users u ON t.user_id = u.id
        #     ORDER BY t.created_at DESC
        # """, (user_id, user_id))
        
        cur.execute("""
    SELECT 
        t.id, t.content, t.created_at, u.name, u.username, u.profile_pic_base64,
        (SELECT COUNT(*) FROM likes l WHERE l.tweet_id = t.id) AS like_count,
        (SELECT COUNT(*) FROM retweets r WHERE r.tweet_id = t.id) AS retweet_count,
        (SELECT COUNT(*) FROM comments c WHERE c.tweet_id = t.id) AS comment_count,
        (SELECT 1 FROM likes l WHERE l.tweet_id = t.id AND l.user_id = %s LIMIT 1) AS user_liked,
        (SELECT 1 FROM retweets r WHERE r.tweet_id = t.id AND r.user_id = %s LIMIT 1) AS user_retweeted,
        (SELECT 1 FROM bookmarks b WHERE b.tweet_id = t.id AND b.user_id = %s LIMIT 1) AS user_bookmarked
    FROM tweets t
    JOIN users u ON t.user_id = u.id
    ORDER BY t.created_at DESC
""", (user_id, user_id, user_id))

        
        tweets = cur.fetchall()

        # Fetch comments for each tweet
        tweet_comments = {}
        for tweet in tweets:
            tweet_id = tweet[0]
            cur.execute("""
                SELECT c.content, c.created_at, u.name, u.username, u.profile_pic_base64
                FROM comments c
                JOIN users u ON c.user_id = u.id
                WHERE c.tweet_id = %s
                ORDER BY c.created_at DESC
            """, (tweet_id,))
            comments = cur.fetchall()
            tweet_comments[tweet_id] = comments

        # Fetch unread notification count
        unread_count = get_unread_notification_count(user_id)

        cur.close()

        if user:
            name, username, email, profile_pic_base64 = user
            return render_template(
                'home.html',
                name=name,
                username=username,
                email=email,
                profile_pic_base64=profile_pic_base64,
                tweets=tweets,
                tweet_comments=tweet_comments,
                unread_count=unread_count
            )
        else:
            flash("User not found.", "danger")
            return redirect(url_for('index'))

    except Exception as e:
        flash(f"Error loading home page: {str(e)}", "danger")
        return redirect(url_for('index'))

@app.route('/tweet', methods=['POST'])
def tweet():
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to tweet"}), 401

    user_id = session['user_id']
    content = request.form.get('content')

    if not content or len(content.strip()) == 0:
        flash("Tweet cannot be empty!", "danger")
        return redirect(url_for('home'))

    if len(content) > 280:
        flash("Tweet cannot exceed 280 characters!", "danger")
        return redirect(url_for('home'))

    try:
        cur = mysql.connection.cursor()
        args = [user_id, content, 0]
        cur.callproc('create_tweet', args)
        mysql.connection.commit()
        
        # Fetch the OUT parameter
        cur.execute("SELECT @_create_tweet_2")
        tweet_id = cur.fetchone()[0]
        
        mentions = re.findall(r'@(\w+)', content)
        if mentions:
            format_strings = ','.join(['%s'] * len(mentions))
            cur.execute(f"SELECT id, username FROM users WHERE username IN ({format_strings})", tuple(mentions))
            mentioned_users = cur.fetchall()

            for mentioned_user in mentioned_users:
                mentioned_user_id = mentioned_user[0]
                # Avoid notifying yourself
                if mentioned_user_id != user_id:
                    cur.execute("""
                        INSERT INTO notifications (user_id, type, from_user_id, tweet_id)
                        VALUES (%s, 'mention', %s, %s)
                    """, (mentioned_user_id, user_id, tweet_id))
                    
        # Handle hashtags
        hashtags = re.findall(r'#(\w+)', content)
        if hashtags:
            # Insert new hashtags into hashtags table (ignore duplicates)
            for hashtag in hashtags:
                cur.execute("""
                    INSERT IGNORE INTO hashtags (hashtag)
                    VALUES (%s)
                """, (f"#{hashtag}",))
            
            mysql.connection.commit()
            
            # Get hashtag IDs
            format_strings = ','.join(['%s'] * len(hashtags))
            cur.execute(f"SELECT id, hashtag FROM hashtags WHERE hashtag IN ({format_strings})", tuple(f"#{h}" for h in hashtags))
            hashtag_rows = cur.fetchall()
            
            # Associate hashtags with the tweet
            for hashtag_row in hashtag_rows:
                hashtag_id = hashtag_row[0]
                cur.execute("""
                    INSERT INTO tweet_hashtags (tweet_id, hashtag_id)
                    VALUES (%s, %s)
                """, (tweet_id, hashtag_id))
        
        mysql.connection.commit()
        cur.close()
        
        flash("Tweet posted successfully!", "success")
        return redirect(url_for('home'))

    except Exception as e:
        flash(f"Failed to post tweet: {str(e)}", "danger")
        return redirect(url_for('home'))

@app.route('/like/<int:tweet_id>', methods=['POST'])
def like(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to like a tweet"}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        args = [user_id, tweet_id, 0]
        cur.callproc('like_tweet', args)
        mysql.connection.commit()
        
        cur.execute("SELECT @_like_tweet_2")
        success = cur.fetchone()[0]

        # Fetch updated like count
        cur.execute("SELECT COUNT(*) FROM likes WHERE tweet_id = %s", (tweet_id,))
        like_count = cur.fetchone()[0]
        cur.close()

        if success:
            return jsonify({"success": True, "like_count": like_count})
        else:
            return jsonify({"success": False, "message": "You have already liked this tweet."}), 400

    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to like tweet: {str(e)}"}), 500

@app.route('/unlike/<int:tweet_id>', methods=['POST'])
def unlike(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to unlike a tweet"}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        args = [user_id, tweet_id, 0]
        cur.callproc('unlike_tweet', args)
        mysql.connection.commit()
        
        cur.execute("SELECT @_unlike_tweet_2")
        success = cur.fetchone()[0]

        # Fetch updated like count
        cur.execute("SELECT COUNT(*) FROM likes WHERE tweet_id = %s", (tweet_id,))
        like_count = cur.fetchone()[0]
        cur.close()

        if success:
            return jsonify({"success": True, "like_count": like_count})
        else:
            return jsonify({"success": False, "message": "Failed to unlike tweet."}), 400

    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to unlike tweet: {str(e)}"}), 500

@app.route('/retweet/<int:tweet_id>', methods=['POST'])
def retweet(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to retweet"}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        args = [user_id, tweet_id, 0]
        cur.callproc('retweet', args)
        mysql.connection.commit()
        
        cur.execute("SELECT @_retweet_2")
        retweet_id = cur.fetchone()[0]

        # Fetch updated retweet count
        cur.execute("SELECT COUNT(*) FROM retweets WHERE tweet_id = %s", (tweet_id,))
        retweet_count = cur.fetchone()[0]
        cur.close()

        if retweet_id:
            return jsonify({"success": True, "retweet_count": retweet_count})
        else:
            return jsonify({"success": False, "message": "You have already retweeted this tweet."}), 400

    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to retweet: {str(e)}"}), 500

@app.route('/unretweet/<int:tweet_id>', methods=['POST'])
def unretweet(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to unretweet"}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        args = [user_id, tweet_id, 0]
        cur.callproc('unretweet', args)
        mysql.connection.commit()
        
        cur.execute("SELECT @_unretweet_2")
        success = cur.fetchone()[0]

        # Fetch updated retweet count
        cur.execute("SELECT COUNT(*) FROM retweets WHERE tweet_id = %s", (tweet_id,))
        retweet_count = cur.fetchone()[0]
        cur.close()

        if success:
            return jsonify({"success": True, "retweet_count": retweet_count})
        else:
            return jsonify({"success": False, "message": "Failed to unretweet."}), 400

    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to unretweet: {str(e)}"}), 500

@app.route('/comment/<int:tweet_id>', methods=['POST'])
def comment(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to comment"}), 401

    user_id = session['user_id']
    content = request.form.get('comment_content')

    if not content or len(content.strip()) == 0:
        return jsonify({"success": False, "message": "Comment cannot be empty!"}), 400

    if len(content) > 280:
        return jsonify({"success": False, "message": "Comment cannot exceed 280 characters!"}), 400

    try:
        cur = mysql.connection.cursor()
        args = [user_id, tweet_id, content, 0]
        cur.callproc('create_comment', args)
        mysql.connection.commit()
        
        cur.execute("SELECT @_create_comment_3")
        comment_id = cur.fetchone()[0]

        # Fetch updated comment count
        cur.execute("SELECT COUNT(*) FROM comments WHERE tweet_id = %s", (tweet_id,))
        comment_count = cur.fetchone()[0]

        # Fetch the new comment details
        cur.execute("""
            SELECT c.content, c.created_at, u.name, u.username, u.profile_pic_base64
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.tweet_id = %s
            ORDER BY c.created_at DESC
            LIMIT 1
        """, (tweet_id,))
        comment = cur.fetchone()
        cur.close()

        if comment_id:
            return jsonify({
                "success": True,
                "comment_count": comment_count,
                "comment": {
                    "content": comment[0],
                    "created_at": comment[1].strftime('%b %d, %Y %H:%M'),
                    "name": comment[2],
                    "username": comment[3],
                    "profile_pic_base64": comment[4]
                }
            })
        else:
            return jsonify({"success": False, "message": "Failed to post comment."}), 400

    except Exception as e:
        return jsonify({"success": False, "message": f"Failed to post comment: {str(e)}"}), 500

@app.route('/edit-profile', methods=['GET', 'POST'])
def edit_profile():
    if 'user_id' not in session:
        return redirect(url_for('signin1'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    if request.method == 'POST':
        try:
            name = request.form['name']
            username = request.form['username']
            email = request.form['email']
            phone = request.form['phone']
            location = request.form.get('location')
            bio = request.form.get('bio')

            
            # Handle profile picture (optional)
            profile_pic = request.files.get('profile_pic')
            if profile_pic and profile_pic.filename != '':
                profile_pic_base64 = base64.b64encode(profile_pic.read()).decode('utf-8')
            else:
                # Keep existing image if none uploaded
                cur.execute("SELECT profile_pic_base64 FROM users WHERE id = %s", (user_id,))
                profile_pic_base64 = cur.fetchone()[0]

            args = [user_id, name, username, email, phone, profile_pic_base64,location,bio]
            cur.callproc('update_user_profile', args)
            mysql.connection.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for('home'))

        except Exception as e:
            flash(f"Failed to update profile: {str(e)}", "danger")
            return redirect(url_for('edit_profile'))

    # GET request: Fetch current user details
    cur.execute("SELECT name, username, email, phone, dob, profile_pic_base64,location,bio FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()

    return render_template('edit_profile.html', user=user)

@app.route('/profile', defaults={'username': None})
@app.route('/profile/<username>')
def profile(username):
    logged_in_user_id = session.get('user_id')
    cursor = mysql.connection.cursor()

    # If no username is provided, get the logged-in user's username
    if username is None:
        cursor.execute("SELECT username FROM users WHERE id = %s", (logged_in_user_id,))
        result = cursor.fetchone()
        if result:
            username = result[0]
        else:
            flash('User not found.', 'error')
            return redirect(url_for('home'))

    # Fetch user details using username
    cursor.execute("""
        SELECT id, name, bio,location,username, profile_pic_base64, created_at,isVerified 
        FROM users 
        WHERE username = %s
    """, (username,))
    user = cursor.fetchone()
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('home'))

    user_id, name, bio,location,username, profile_pic_base64, created_at,isVerified = user

    # Fetch follower and following counts
    cursor.execute("SELECT COUNT(*) FROM followers WHERE following_id = %s", (user_id,))
    follower_count = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM followers WHERE follower_id = %s", (user_id,))
    following_count = cursor.fetchone()[0]

    # Check if the logged-in user is following this user
    is_following = False
    if user_id != logged_in_user_id:
        cursor.execute("""
            SELECT EXISTS(
                SELECT 1 FROM followers 
                WHERE follower_id = %s AND following_id = %s
            )
        """, (logged_in_user_id, user_id))
        is_following = cursor.fetchone()[0] == 1

    # Fetch user's tweets
    cursor.execute("""
        SELECT 
            t.id, t.content, t.created_at, 
            u.name, u.username, u.profile_pic_base64,
            (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id) AS like_count,
            (SELECT COUNT(*) FROM retweets WHERE tweet_id = t.id) AS retweet_count,
            (SELECT COUNT(*) FROM comments WHERE tweet_id = t.id) AS comment_count,
            EXISTS(SELECT 1 FROM likes WHERE tweet_id = t.id AND user_id = %s) AS user_liked,
            EXISTS(SELECT 1 FROM retweets WHERE tweet_id = t.id AND user_id = %s) AS user_retweeted,
            'tweet' AS type
        FROM tweets t
        JOIN users u ON t.user_id = u.id
        WHERE t.user_id = %s
    """, (logged_in_user_id, logged_in_user_id, user_id))
    user_tweets = cursor.fetchall()

    # Fetch user's retweets
    cursor.execute("""
        SELECT 
            t.id, t.content, t.created_at, 
            u.name, u.username, u.profile_pic_base64,
            (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id) AS like_count,
            (SELECT COUNT(*) FROM retweets WHERE tweet_id = t.id) AS retweet_count,
            (SELECT COUNT(*) FROM comments WHERE tweet_id = t.id) AS comment_count,
            EXISTS(SELECT 1 FROM likes WHERE tweet_id = t.id AND user_id = %s) AS user_liked,
            EXISTS(SELECT 1 FROM retweets WHERE tweet_id = t.id AND user_id = %s) AS user_retweeted,
            'retweet' AS type,
            u2.username AS retweeter_username
        FROM retweets r
        JOIN tweets t ON r.tweet_id = t.id
        JOIN users u ON t.user_id = u.id
        JOIN users u2 ON r.user_id = u2.id
        WHERE r.user_id = %s
    """, (logged_in_user_id, logged_in_user_id, user_id))
    user_retweets = cursor.fetchall()

    # Combine and sort timeline
    timeline = list(user_tweets) + list(user_retweets)
    timeline.sort(key=lambda x: x[2], reverse=True)

    # Process timeline data
    timeline_data = []
    for item in timeline:
        profile_pic = item[5]
        timeline_data.append(item[:5] + (profile_pic,) + item[6:])

    # Fetch comments for each tweet/retweet in the timeline
    tweet_comments = {}
    for item in timeline:
        tweet_id = item[0]
        cursor.execute("""
            SELECT c.content, c.created_at, u.name, u.username, u.profile_pic_base64
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.tweet_id = %s
            ORDER BY c.created_at DESC
        """, (tweet_id,))
        comments = cursor.fetchall()
        tweet_comments[tweet_id] = [
            (comment[0], comment[1], comment[2], comment[3], comment[4])
            for comment in comments
        ]

    # Fetch unread notification count
    unread_count = get_unread_notification_count(logged_in_user_id)

    cursor.close()
    return render_template('profile.html', 
                         name=name, 
                         username=username, 
                         profile_pic_base64=profile_pic_base64, 
                         created_at=created_at,
                         bio=bio,
                         location=location,
                         is_verified=isVerified,
                         timeline=timeline_data, 
                         tweet_comments=tweet_comments,
                         follower_count=follower_count,
                         following_count=following_count,
                         is_following=is_following,
                         user_id=user_id,
                         logged_in_user_id=logged_in_user_id,
                         unread_count=unread_count)

@app.route('/follow/<int:user_id>', methods=['POST'])
def follow(user_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to follow."}), 401

    logged_in_user_id = session['user_id']
    if logged_in_user_id == user_id:
        return jsonify({"success": False, "message": "You cannot follow yourself."}), 400

    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""
            INSERT INTO followers (follower_id, following_id) 
            VALUES (%s, %s)
        """, (logged_in_user_id, user_id))
        mysql.connection.commit()

        # Fetch updated follower count
        cursor.execute("SELECT COUNT(*) FROM followers WHERE following_id = %s", (user_id,))
        follower_count = cursor.fetchone()[0]

        return jsonify({"success": True, "follower_count": follower_count})
    except mysql.connection.Error as err:
        mysql.connection.rollback()
        return jsonify({"success": False, "message": "You are already following this user."}), 400
    finally:
        cursor.close()

@app.route('/unfollow/<int:user_id>', methods=['POST'])
def unfollow(user_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in to unfollow."}), 401

    logged_in_user_id = session['user_id']
    cursor = mysql.connection.cursor()
    try:
        cursor.execute("""
            DELETE FROM followers 
            WHERE follower_id = %s AND following_id = %s
        """, (logged_in_user_id, user_id))
        mysql.connection.commit()

        # Fetch updated follower count
        cursor.execute("SELECT COUNT(*) FROM followers WHERE following_id = %s", (user_id,))
        follower_count = cursor.fetchone()[0]

        return jsonify({"success": True, "follower_count": follower_count})
    except mysql.connection.Error as err:
        mysql.connection.rollback()
        return jsonify({"success": False, "message": "Error unfollowing user."}), 400
    finally:
        cursor.close()
        
@app.route('/mention-suggestions')
def mention_suggestions():
    query = request.args.get('q', '')
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT name, username, profile_pic_base64 
        FROM users 
        WHERE username LIKE %s 
        LIMIT 10
    """, (query + '%',))
    results = cursor.fetchall()
    cursor.close()

    suggestions = [{
        'name': row[0],
        'username': row[1],
        'profile_pic_base64': row[2]
    } for row in results]

    return jsonify(suggestions)

@app.route('/hashtag-suggestions')
def hashtag_suggestions():
    query = request.args.get('q', '')
    cursor = mysql.connection.cursor()
    cursor.execute("""
        SELECT hashtag 
        FROM hashtags 
        WHERE hashtag LIKE %s 
        LIMIT 10
    """, ('#' + query + '%',))
    results = cursor.fetchall()
    cursor.close()

    suggestions = [{'hashtag': row[0]} for row in results]
    return jsonify(suggestions)


@app.route('/notifications')
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()

    # Fetch user details
    cur.execute("SELECT name, username, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()

    # Fetch notifications
    cur.execute("""
        SELECT n.id, n.type, u.username, u.name, u.profile_pic_base64, n.tweet_id, n.created_at, n.is_read
        FROM notifications n
        JOIN users u ON n.from_user_id = u.id
        WHERE n.user_id = %s
        ORDER BY n.created_at DESC
        LIMIT 50
    """, (user_id,))
    notifications = cur.fetchall()

    # Fetch unread notification count
    unread_count = get_unread_notification_count(user_id)

    cur.close()

    if user:
        name, username, profile_pic_base64 = user
        return render_template(
            'notifications.html',
            notifications=notifications,
            name=name,
            username=username,
            profile_pic_base64=profile_pic_base64,
            unread_count=unread_count
        )
    else:
        flash("User not found.", "danger")
        return redirect(url_for('index'))

@app.route('/mark-notification-read/<int:notification_id>', methods=['POST'])
def mark_notification_read(notification_id):
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        cur.execute("""
            UPDATE notifications 
            SET is_read = TRUE 
            WHERE id = %s AND user_id = %s
        """, (notification_id, user_id))
        mysql.connection.commit()
        cur.close()

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/tweet/<int:tweet_id>')
def view_tweet(tweet_id):
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id = session['user_id']
    cursor = mysql.connection.cursor()

    # Fetch user details
    cursor.execute("SELECT name, username, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
    user = cursor.fetchone()

    cursor.execute("""
        SELECT t.id, t.content, t.created_at, u.name, u.username, u.profile_pic_base64
        FROM tweets t
        JOIN users u ON t.user_id = u.id
        WHERE t.id = %s
    """, (tweet_id,))
    tweet = cursor.fetchone()

    if not tweet:
        cursor.close()
        return "Tweet not found", 404

    cursor.execute("""
        SELECT c.content, c.created_at, u.name, u.username, u.profile_pic_base64
        FROM comments c
        JOIN users u ON c.user_id = u.id
        WHERE c.tweet_id = %s
        ORDER BY c.created_at DESC
    """, (tweet_id,))
    comments = cursor.fetchall()

    # Fetch unread notification count
    unread_count = get_unread_notification_count(user_id)

    cursor.close()

    if user:
        name, username, profile_pic_base64 = user
        return render_template(
            'view_tweet.html',
            tweet=tweet,
            comments=comments,
            name=name,
            username=username,
            profile_pic_base64=profile_pic_base64,
            unread_count=unread_count
        )
    else:
        flash("User not found.", "danger")
        return redirect(url_for('index'))

def format_mentions(content):
    """Convert @username mentions into clickable links."""
    def replace_mention(match):
        username = match.group(1)
        return f'<a href="/profile/{username}" class="text-blue-500 hover:underline">@{username}</a>'
    return re.sub(r'@(\w+)', replace_mention, content)

app.jinja_env.filters['format_mentions'] = format_mentions

def is_logged_in():
    return 'user_id' in session

@app.route('/verify', methods=['POST'])
def verify():
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({"error": "User not logged in"}), 401

    cursor = mysql.connection.cursor()
    query = "UPDATE users SET isVerified = 1 WHERE id = %s"
    cursor.execute(query, (user_id,))
    mysql.connection.commit()
    cursor.close()

    return jsonify({"message": "User verified successfully"})
@app.route('/bookmarks')
def bookmarks():
    if 'user_id' not in session:
        return redirect(url_for('index'))

    user_id = session['user_id']
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT 
            t.id, t.content, t.created_at, u.name, u.username, u.profile_pic_base64,
            (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id),
            (SELECT COUNT(*) FROM retweets WHERE tweet_id = t.id),
            (SELECT COUNT(*) FROM comments WHERE tweet_id = t.id),
            EXISTS(SELECT 1 FROM likes WHERE tweet_id = t.id AND user_id = %s),
            EXISTS(SELECT 1 FROM retweets WHERE tweet_id = t.id AND user_id = %s),
            EXISTS(SELECT 1 FROM bookmarks WHERE tweet_id = t.id AND user_id = %s)
        FROM bookmarks b
        JOIN tweets t ON b.tweet_id = t.id
        JOIN users u ON t.user_id = u.id
        WHERE b.user_id = %s
        ORDER BY b.created_at DESC
    """, (user_id, user_id, user_id, user_id))
    tweets = cur.fetchall()

    tweet_comments = {}
    for tweet in tweets:
        tweet_id = tweet[0]
        cur.execute("""
            SELECT c.content, c.created_at, u.name, u.username, u.profile_pic_base64
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.tweet_id = %s
            ORDER BY c.created_at DESC
        """, (tweet_id,))
        tweet_comments[tweet_id] = cur.fetchall()

    unread_count = get_unread_notification_count(user_id)

    cur.execute("SELECT name, username, email, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()

    return render_template(
        'home.html',
        tweets=tweets,
        tweet_comments=tweet_comments,
        unread_count=unread_count,
        name=user[0],
        username=user[1],
        email=user[2],
        profile_pic_base64=user[3]
    )


@app.route('/bookmark/<int:tweet_id>', methods=['POST'])
def bookmark(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in"}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        cur.execute("INSERT IGNORE INTO bookmarks (user_id, tweet_id) VALUES (%s, %s)", (user_id, tweet_id))
        mysql.connection.commit()
        cur.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/unbookmark/<int:tweet_id>', methods=['POST'])
def unbookmark(tweet_id):
    if 'user_id' not in session:
        return jsonify({"success": False, "message": "Please log in"}), 401

    user_id = session['user_id']
    try:
        cur = mysql.connection.cursor()
        cur.execute("DELETE FROM bookmarks WHERE user_id = %s AND tweet_id = %s", (user_id, tweet_id))
        mysql.connection.commit()
        cur.close()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/search')
def search():
    query = request.args.get('q', '').strip()
    user_id = session.get('user_id')

    if not user_id or not query:
        return redirect(url_for('home'))

    cur = mysql.connection.cursor()

    # Search for users
    cur.execute("""
        SELECT id, name, username, profile_pic_base64 
        FROM users 
        WHERE (name LIKE %s OR username LIKE %s) AND isActive = 1
        LIMIT 20
    """, (f'%{query}%', f'%{query}%'))
    users = cur.fetchall()

    # Search for tweets
    cur.execute("""
        SELECT 
            t.id, t.content, t.created_at, u.name, u.username, u.profile_pic_base64,
            (SELECT COUNT(*) FROM likes WHERE tweet_id = t.id),
            (SELECT COUNT(*) FROM retweets WHERE tweet_id = t.id),
            (SELECT COUNT(*) FROM comments WHERE tweet_id = t.id),
            EXISTS(SELECT 1 FROM likes WHERE tweet_id = t.id AND user_id = %s),
            EXISTS(SELECT 1 FROM retweets WHERE tweet_id = t.id AND user_id = %s),
            EXISTS(SELECT 1 FROM bookmarks WHERE tweet_id = t.id AND user_id = %s)
        FROM tweets t
        JOIN users u ON t.user_id = u.id
        WHERE t.content LIKE %s
        ORDER BY t.created_at DESC
        LIMIT 50
    """, (user_id, user_id, user_id, f'%{query}%'))
    tweets = cur.fetchall()

    # Fetch comments for each matching tweet
    tweet_comments = {}
    for tweet in tweets:
        tweet_id = tweet[0]
        cur.execute("""
            SELECT c.content, c.created_at, u.name, u.username, u.profile_pic_base64
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.tweet_id = %s
            ORDER BY c.created_at DESC
        """, (tweet_id,))
        tweet_comments[tweet_id] = cur.fetchall()

    cur.execute("SELECT name, username, email, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    unread_count = get_unread_notification_count(user_id)

    cur.close()

    return render_template(
        'home.html',
        query=query,
        users=users,
        tweets=tweets,
        tweet_comments=tweet_comments,
        name=user[0],
        username=user[1],
        email=user[2],
        profile_pic_base64=user[3],
        unread_count=unread_count
    )


@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))


@app.route('/deactivate-account', methods=['POST'])
def deactivate_account():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"success": False, "error": "User not logged in"}), 401
    
    try:
        cursor = mysql.connection.cursor()
        query = "UPDATE users SET isActive = 0 WHERE id = %s"
        cursor.execute(query, (user_id,))
        mysql.connection.commit()
        cursor.close()
        session.clear()
        return jsonify({"success": True, "message": "Account has been deactivated."})
    except Exception as e:
        return jsonify({"success": False, "error": "Failed to deactivate account due to a server error."}), 500

if __name__ == '__main__':
    app.run(debug=True)