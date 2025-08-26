from flask import Blueprint, request, jsonify, session, current_app
import asyncio
import json
import os
from downloader import download_books, AudiobookDownloader

download_bp = Blueprint('download', __name__)

def load_accounts():
    """Load saved Audible accounts from JSON file"""
    accounts_file = current_app.config['ACCOUNTS_FILE']
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r') as f:
            return json.load(f)
    return {}

@download_bp.route('/api/download/books', methods=['POST'])
def download_selected_books():
    """API endpoint to download selected books"""
    data = request.get_json()
    selected_asins = data.get('selected_asins', [])
    cleanup_aax = data.get('cleanup_aax', True)
    
    if not selected_asins:
        return jsonify({'error': 'No books selected for download'}), 400
    
    current_account = session.get('current_account')
    if not current_account:
        return jsonify({'error': 'No account selected'}), 400
    
    accounts = load_accounts()
    if current_account not in accounts:
        return jsonify({'error': 'Account not found'}), 404
    
    account_data = accounts[current_account]
    region = account_data['region']
    
    # Fetch library directly since session storage is too large for browser cookies
    from auth import fetch_library
    library = asyncio.run(fetch_library(current_account, region))
    
    if not library:
        return jsonify({'error': 'Failed to fetch library for download'}), 400
    
    # Get selected book details
    selected_books = [
        book for book in library 
        if book['asin'] in selected_asins
    ]
    
    if not selected_books:
        return jsonify({'error': 'Selected books not found in library'}), 400
    
    try:
        # Set cleanup preference in session
        session['cleanup_aax'] = cleanup_aax
        
        # Start download process asynchronously
        results = asyncio.run(download_books(
            current_account,
            region,
            selected_books,
            cleanup_aax=cleanup_aax
        ))
        
        successful_downloads = len([r for r in results if r])
        
        return jsonify({
            'success': True,
            'message': f'Download completed! {successful_downloads} of {len(selected_books)} books downloaded successfully.',
            'results': results
        })
        
    except Exception as e:
        return jsonify({'error': f'Download error: {str(e)}'}), 500

@download_bp.route('/api/download/status/<asin>')
def download_status_asin(asin):
    """API endpoint to check download status for a specific book"""
    downloader = AudiobookDownloader(session.get('current_account'), session.get('region'))
    state = downloader.get_download_state(asin)
    return jsonify(state)

@download_bp.route('/api/download/status')
def download_status():
    """API endpoint to check download status (placeholder for future implementation)"""
    return jsonify({'status': 'idle'})