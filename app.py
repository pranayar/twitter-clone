from flask import Flask, request, render_template, redirect, flash, jsonify,session, url_for
from flask_mysqldb import MySQL
from werkzeug.security import generate_password_hash, check_password_hash
import base64

app = Flask(__name__)
app.secret_key = 'your_secret_key'
#https://upload.wikimedia.org/wikipedia/commons/5/53/X_logo_2023_original.svg
# DB config
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'abcd6658'
app.config['MYSQL_DB'] = 'twitter_clone'
mysql = MySQL(app)
#ctrl k ctrl 0 
@app.route('/')
def index():
    # Simulate some loading task (e.g., data fetching or processing) 
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
                return render_template('signup/signup1.html', error="Email already registered")
            else:
                print("Database error during signup:", err)
                return redirect(url_for('signup'))
        except Exception as e:
            print("Exception during signup:", e)
            return redirect(url_for('signup'))

    return render_template('signup/signup1.html')


@app.route('/check-identifier', methods=['POST'])
def check_identifier():
    data = request.json
    identifier = data.get('identifier')

    if not identifier:
        return jsonify({"error": "Identifier is required"}), 400

    cursor = mysql.connection.cursor()
    query = """
        SELECT 1 FROM users
        WHERE phone = %s OR email = %s OR username = %s
        LIMIT 1;
    """
    cursor.execute(query, (identifier, identifier, identifier))
    result = cursor.fetchone()
    cursor.close()

    if result:
        return jsonify({"message": "User already exists", "exists": True})
    else:
        return jsonify({"message": "User not found", "exists": False})
    

@app.route('/signin1', methods=['GET', 'POST'])
def singIn1():
    return render_template('signin1.html')

@app.route('/signin2', methods=['GET', 'POST'])
def singIn2():
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
        return redirect(url_for('signin1'))  

    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT name, username, email, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        cur.close()

        if user:
            name, username, email, profile_pic_base64 = user
            return render_template(
                'home.html',
                name=name,
                username=username,
                email=email,
                profile_pic_base64=profile_pic_base64
            )
        else:
            flash("User not found.", "danger")
            return redirect(url_for('index'))

    except Exception as e:
        flash(f"Error loading home page: {str(e)}", "danger")
        return redirect(url_for('index'))
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
            

            # Handle profile picture (optional)
            profile_pic = request.files.get('profile_pic')
            if profile_pic and profile_pic.filename != '':
                profile_pic_base64 = base64.b64encode(profile_pic.read()).decode('utf-8')
            else:
                # Keep existing image if none uploaded
                cur.execute("SELECT profile_pic_base64 FROM users WHERE id = %s", (user_id,))
                profile_pic_base64 = cur.fetchone()[0]

            args = [user_id, name, username, email, phone, profile_pic_base64]
            cur.callproc('update_user_profile', args)
            mysql.connection.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for('home'))

        except Exception as e:
            flash(f"Failed to update profile: {str(e)}", "danger")
            return redirect(url_for('edit_profile'))

    # GET request: Fetch current user details
    cur.execute("SELECT name, username, email, phone, dob, profile_pic_base64 FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()

    return render_template('edit_profile.html', user=user)

@app.route('/post-tweet', methods=['POST'])
def post_tweet():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401

    user_id = session['user_id']
    content = request.form.get('content', '').strip()

    if not content or len(content) > 280:
        return jsonify({'error': 'Invalid tweet content'}), 400

    cur = mysql.connection.cursor()
    try:
        cur.callproc('add_tweet', [user_id, content])
        mysql.connection.commit()
        return jsonify({'message': 'Tweet posted successfully'}), 201
    except Exception as e:
        mysql.connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()




@app.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(debug=True)