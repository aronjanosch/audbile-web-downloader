from flask import Blueprint, request, jsonify, session, current_app, render_template, redirect, url_for
import asyncio
import json
import os
from threading import Event, Thread
from auth import authenticate_account, fetch_library, AudibleAuth
from audible.login import external_login
from audible.localization import Locale, search_template

auth_bp = Blueprint('auth', __name__)

def load_accounts():
    """Load saved Audible accounts from JSON file"""
    accounts_file = current_app.config['ACCOUNTS_FILE']
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r') as f:
            return json.load(f)
    return {}

def save_accounts(accounts):
    """Save Audible accounts to JSON file"""
    accounts_file = current_app.config['ACCOUNTS_FILE']
    with open(accounts_file, 'w') as f:
        json.dump(accounts, f, indent=2)

@auth_bp.route('/api/auth/authenticate', methods=['POST'])
def authenticate():
    """API endpoint to authenticate an account with Audible"""
    data = request.get_json()
    account_name = data.get('account_name')
    
    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400
    
    accounts = load_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[account_name]
    region = account_data['region']
    
    try:
        # Run authentication asynchronously
        auth = asyncio.run(authenticate_account(account_name, region))
        
        if auth:
            accounts[account_name]['authenticated'] = True
            save_accounts(accounts)
            return jsonify({'success': True, 'message': 'Authentication successful'})
        else:
            return jsonify({'error': 'Authentication failed'}), 400
            
    except Exception as e:
        return jsonify({'error': f'Authentication error: {str(e)}'}), 500

@auth_bp.route('/api/auth/check', methods=['POST'])
def check_auth():
    """API endpoint to check if an account is authenticated"""
    data = request.get_json()
    account_name = data.get('account_name')
    
    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400
    
    accounts = load_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[account_name]
    region = account_data['region']
    
    # Check if we have a valid auth file
    from pathlib import Path
    import audible
    
    config_dir = Path(f".audible_{account_name}")
    auth_file = config_dir / "auth.json"
    
    is_authenticated = False
    if auth_file.exists():
        try:
            # Try to load the authenticator - if it works, we're authenticated
            auth = audible.Authenticator.from_file(auth_file)
            is_authenticated = True
        except Exception:
            # If loading fails, we're not authenticated
            is_authenticated = False
    
    # Update account data if status changed
    if accounts[account_name].get('authenticated') != is_authenticated:
        accounts[account_name]['authenticated'] = is_authenticated
        save_accounts(accounts)
    
    return jsonify({'authenticated': is_authenticated})

# Store for active login sessions
login_sessions = {}

@auth_bp.route('/auth/login/<account_name>')
def start_login(account_name):
    """Start the Audible login process"""
    accounts = load_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[account_name]
    region = account_data['region']
    
    # Get localization data
    template = search_template('country_code', region)
    if not template:
        return jsonify({'error': f'Unsupported region: {region}'}), 400
    loc = Locale(**template)
    
    # Create login session
    session_id = f"{account_name}_{len(login_sessions)}"
    login_event = Event()
    login_result = {}
    
    def web_login_callback(oauth_url):
        """Custom callback that stores the URL and waits for user input"""
        login_sessions[session_id] = {
            'oauth_url': oauth_url,
            'event': login_event,
            'result': login_result,
            'account_name': account_name
        }
        
        # Wait for user to complete login
        login_event.wait(timeout=300)  # 5 minute timeout
        
        if 'response_url' in login_result:
            return login_result['response_url']
        else:
            raise Exception("Login timeout or cancelled")
    
    def login_thread():
        try:
            # Use audible's built-in external login method directly
            import audible
            
            auth = audible.Authenticator.from_login_external(
                locale=loc,
                with_username=False,
                login_url_callback=web_login_callback
            )
            
            # Save authenticator to expected location
            from pathlib import Path
            config_dir = Path(f".audible_{account_name}")
            config_dir.mkdir(exist_ok=True)
            auth_file = config_dir / "auth.json"
            auth.to_file(auth_file, encryption=False)
            
            login_result['success'] = True
            
        except Exception as e:
            login_result['error'] = str(e)
            login_result['success'] = False
    
    # Start login in background thread
    Thread(target=login_thread, daemon=True).start()
    
    # Redirect to login page
    return redirect(url_for('auth.login_page', session_id=session_id))

@auth_bp.route('/auth/login-page/<session_id>')
def login_page(session_id):
    """Display login page with OAuth URL"""
    if session_id not in login_sessions:
        return "Login session not found", 404
    
    session_data = login_sessions[session_id]
    
    # Wait for OAuth URL to be available
    if 'oauth_url' not in session_data:
        return "Login initializing...", 202
    
    return render_template('auth/login.html', 
                         oauth_url=session_data['oauth_url'],
                         session_id=session_id,
                         account_name=session_data['account_name'])

@auth_bp.route('/auth/callback/<session_id>', methods=['POST'])
def login_callback(session_id):
    """Handle the OAuth callback URL from user"""
    if session_id not in login_sessions:
        return jsonify({'error': 'Login session not found'}), 404
    
    data = request.get_json()
    response_url = data.get('response_url')
    
    if not response_url:
        return jsonify({'error': 'Response URL is required'}), 400
    
    session_data = login_sessions[session_id]
    session_data['result']['response_url'] = response_url
    session_data['event'].set()
    
    return jsonify({'success': True, 'message': 'Processing login...'})

@auth_bp.route('/auth/status/<session_id>')
def login_status(session_id):
    """Check login status"""
    if session_id not in login_sessions:
        return jsonify({'error': 'Login session not found'}), 404
    
    session_data = login_sessions[session_id]
    result = session_data['result']
    
    if 'success' in result:
        # Clean up session
        del login_sessions[session_id]
        
        if result['success']:
            # The authenticator should already be created in the login_thread
            # Just mark account as authenticated
            accounts = load_accounts()
            account_name = session_data['account_name']
            accounts[account_name]['authenticated'] = True
            save_accounts(accounts)
            
            return jsonify({
                'success': True, 
                'message': 'Login successful!',
                'redirect': url_for('main.index')
            })
        else:
            return jsonify({
                'success': False, 
                'error': result.get('error', 'Unknown error')
            })
    
    return jsonify({'status': 'pending'})

@auth_bp.route('/api/library/fetch', methods=['POST'])
def fetch_library_route():
    """API endpoint to fetch the user's Audible library"""
    data = request.get_json()
    account_name = data.get('account_name')
    
    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400
    
    accounts = load_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[account_name]
    region = account_data['region']
    
    # Check if authenticated by trying to load the auth file
    from pathlib import Path
    import audible
    
    config_dir = Path(f".audible_{account_name}")
    auth_file = config_dir / "auth.json"
    
    if not auth_file.exists():
        return jsonify({'error': 'Account not authenticated'}), 401
    
    try:
        # Try to load the authenticator - if it fails, we're not authenticated
        auth = audible.Authenticator.from_file(auth_file)
    except Exception:
        return jsonify({'error': 'Account not authenticated'}), 401
    
    try:
        # Simply fetch library using existing authentication file
        # The authenticator should already be saved during login
        library = asyncio.run(fetch_library(account_name, region))
        
        if library:
            # Don't store in session - too large for browser cookies
            return jsonify({
                'success': True, 
                'message': f'Loaded {len(library)} books',
                'library': library
            })
        else:
            return jsonify({'error': 'Failed to load library'}), 500
            
    except Exception as e:
        return jsonify({'error': f'Library fetch error: {str(e)}'}), 500 