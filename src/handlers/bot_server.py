"""
Flask web server for bot webhooks and monitoring.
Optional integration for bot health checks and external API calls.
"""

from flask import Flask, jsonify, request
from datetime import datetime
import logging

from src.core.config import get_config, logger


class BotServer:
    """Web server for bot integration and monitoring."""
    
    def __init__(self, config, bot_core=None):
        self.config = config
        self.bot_core = bot_core
        self.logger = logger
        self.app = Flask(__name__)
        
        # Register routes
        self._register_routes()
    
    def _register_routes(self):
        """Register Flask routes."""
        
        @self.app.route('/health', methods=['GET'])
        def health():
            """Health check endpoint."""
            return jsonify({
                'status': 'online',
                'timestamp': datetime.now().isoformat(),
                'bot_ready': self.bot_core is not None and self.bot_core.bot.user is not None
            })
        
        @self.app.route('/stats', methods=['GET'])
        def stats():
            """Bot statistics endpoint."""
            if not self.bot_core:
                return jsonify({'error': 'Bot not initialized'}), 503
            
            return jsonify({
                'bot_name': str(self.bot_core.bot.user),
                'bot_id': self.bot_core.bot.user.id if self.bot_core.bot.user else None,
                'latency': self.bot_core.bot.latency,
                'guilds': len(self.bot_core.bot.guilds),
                'users': sum(guild.member_count for guild in self.bot_core.bot.guilds) if self.bot_core.bot.guilds else 0
            })
        
        @self.app.route('/api/message', methods=['POST'])
        def send_message():
            """Send message via API (webhook)."""
            if not self.bot_core:
                return jsonify({'error': 'Bot not ready'}), 503
            
            data = request.get_json()
            if not data:
                return jsonify({'error': 'No JSON data'}), 400
            
            user_id = data.get('user_id')
            channel_id = data.get('channel_id')
            message_text = data.get('message')
            
            if not user_id or not message_text:
                return jsonify({'error': 'Missing required fields'}), 400
            
            return jsonify({
                'status': 'queued',
                'message': 'Message queued for sending'
            }), 202
        
        @self.app.route('/api/cache/clear', methods=['POST'])
        def clear_cache():
            """Clear bot cache (admin only)."""
            token = request.headers.get('Authorization', '')
            if token != f"Bearer {self.config.ADMIN_TOKEN}":
                return jsonify({'error': 'Unauthorized'}), 401
            
            # TODO: Clear cache through bot_core
            return jsonify({
                'status': 'cleared',
                'timestamp': datetime.now().isoformat()
            })
        
        @self.app.errorhandler(404)
        def not_found(error):
            return jsonify({'error': 'Not found'}), 404
        
        @self.app.errorhandler(500)
        def internal_error(error):
            self.logger.error(f"Internal server error: {error}")
            return jsonify({'error': 'Internal server error'}), 500
    
    def run(self, host='0.0.0.0', port=5000, debug=False):
        """Run the Flask server."""
        self.logger.info(f"Starting web server on {host}:{port}")
        self.app.run(host=host, port=port, debug=debug)
