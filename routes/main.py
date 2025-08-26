from flask import Blueprint, render_template, request, jsonify, session, current_app
import json
import os
from pathlib import Path

main_bp = Blueprint('main', __name__)

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

@main_bp.route('/')
def index():
    """Main page with account management and library display"""
    accounts = load_accounts()
    current_account = session.get('current_account')
    
    # Get current account data
    current_account_data = None
    if current_account and current_account in accounts:
        current_account_data = accounts[current_account]
    
    # Get library from session
    library = session.get('library', [])
    
    return render_template('index.html', 
                         accounts=accounts,
                         current_account=current_account,
                         current_account_data=current_account_data,
                         library=library)

@main_bp.route('/api/accounts', methods=['GET'])
def get_accounts():
    """API endpoint to get all accounts"""
    accounts = load_accounts()
    return jsonify(accounts)

@main_bp.route('/api/accounts', methods=['POST'])
def add_account():
    """API endpoint to add a new account"""
    data = request.get_json()
    
    if not data:
        return jsonify({'error': 'No JSON data received'}), 400
        
    account_name = data.get('account_name')
    region = data.get('region', 'us')
    
    if not account_name:
        return jsonify({'error': 'Account name is required'}), 400
    
    accounts = load_accounts()
    
    if account_name in accounts:
        return jsonify({'error': 'Account name already exists'}), 400
    
    accounts[account_name] = {
        "region": region,
        "authenticated": False
    }
    
    save_accounts(accounts)
    session['current_account'] = account_name
    
    return jsonify({'success': True, 'account': accounts[account_name]})

@main_bp.route('/api/accounts/<account_name>/select', methods=['POST'])
def select_account(account_name):
    """API endpoint to select an account"""
    accounts = load_accounts()
    
    if account_name not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    session['current_account'] = account_name
    return jsonify({'success': True})

@main_bp.route('/api/library/search')
def search_library():
    """API endpoint to search library"""
    search_term = request.args.get('q', '').lower()
    library = session.get('library', [])
    
    if not search_term:
        return jsonify(library)
    
    filtered_books = [
        book for book in library
        if search_term in book.get('title', '').lower() or 
           search_term in book.get('authors', '').lower()
    ]
    
    return jsonify(filtered_books) 