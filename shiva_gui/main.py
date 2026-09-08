"""
Shiva Support Workflow GUI - PyQt6 Desktop Application

A desktop application for testing the Shiva AI Support Platform workflow.
"""

import sys
import json
import requests
import asyncio
import csv
from datetime import datetime
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QTextEdit, QLineEdit, QComboBox,
    QFormLayout, QGroupBox, QListWidget, QListWidgetItem, QProgressBar,
    QStatusBar, QSplitter, QFrame, QScrollArea, QMessageBox, QDialog,
    QDialogButtonBox, QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor, QPalette


class APIClient:
    """Client for communicating with the Shiva backend API."""
    
    def __init__(self, base_url="http://localhost:8000"):
        self.base_url = base_url
        
    def get_health(self):
        """Check backend health."""
        try:
            response = requests.get(f"{self.base_url}/healthz", timeout=5)
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def seed_mock_database(self):
        """Seed the database with mock data."""
        try:
            response = requests.post(f"{self.base_url}/mock/seed-database", timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def clear_mock_database(self):
        """Clear mock data from database."""
        try:
            response = requests.post(f"{self.base_url}/mock/clear-database", timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_mock_data_info(self):
        """Get mock data information."""
        try:
            response = requests.get(f"{self.base_url}/mock/data-info", timeout=10)
            return response.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def analyze_with_groq(self, message, conversation_history=None):
        """Analyze message using Groq AI via backend REST API endpoint."""
        try:
            # Convert chat history to format expected by backend
            formatted_history = []
            if conversation_history:
                for msg in conversation_history:
                    # Convert GUI format to backend format
                    sender_mapping = {
                        "user": "customer",
                        "ai": "support_ai", 
                        "system": "system"
                    }
                    backend_sender = sender_mapping.get(msg.get("sender", "user"), "customer")
                    formatted_history.append({
                        "sender": backend_sender,
                        "content": msg.get("content", ""),
                        "created_at": msg.get("timestamp", datetime.now().isoformat())
                    })
            
            response = requests.post(
                f"{self.base_url}/test-groq-analysis",
                json={
                    "message": message,
                    "conversation_history": formatted_history,
                    "customer_id": "gui_customer"
                },
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}",
                    "details": response.text
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}
    
    def get_groq_analysis(self, message, conversation_history=None):
        """Get Groq analysis - alias for analyze_with_groq."""
        return self.analyze_with_groq(message, conversation_history)
    
    def get_ai_resolved_tickets(self):
        """Get AI resolved tickets from backend."""
        try:
            graphql_query = """
            query {
                aiResolvedTickets(limit: 50) {
                    id
                    customer_id
                    status
                    chat_summary
                    ai_resolution_feedback
                    ai_resolution_confidence
                    messages {
                        sender
                        content
                        created_at
                    }
                }
            }
            """
            
            response = requests.post(
                f"{self.base_url}/graphql",
                json={"query": graphql_query},
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                if "data" in data and "aiResolvedTickets" in data["data"]:
                    return {
                        "status": "success",
                        "tickets": data["data"]["aiResolvedTickets"]
                    }
                else:
                    return {
                        "status": "error",
                        "error": "Invalid response format",
                        "response": data
                    }
            else:
                return {
                    "status": "error",
                    "error": f"HTTP {response.status_code}",
                    "details": response.text
                }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _staff_headers(self, staff_id):
        tokens = {
            "staff_001": "mock_token_staff",
            "staff_002": "mock_token_staff_002",
            "staff_003": "mock_token_staff_003",
        }
        return {"Content-Type": "application/json", "Authorization": f"Bearer {tokens[staff_id]}"}

    def get_assigned_tickets(self, staff_id):
        query = """query { staffDashboardTickets { id customerId status assignedStaffId chatSummary } }"""
        try:
            response = requests.post(f"{self.base_url}/graphql", json={"query": query},
                headers=self._staff_headers(staff_id), timeout=30)
            data = response.json()
            if response.status_code == 200 and data.get("data"):
                return {"status": "success", "tickets": data["data"]["staffDashboardTickets"]}
            return {"status": "error", "error": data.get("errors", response.text)}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def reply_to_ticket(self, staff_id, ticket_id, content):
        query = """mutation($input: ReplyToTicketInput!) { replyToTicket(input: $input) { id ticketId content createdAt } }"""
        return self._staff_mutation(staff_id, query, {"input": {"ticketId": ticket_id, "content": content}})

    def close_staff_ticket(self, staff_id, ticket_id):
        query = """mutation($input: CloseTicketInput!) { closeTicket(input: $input) { id status } }"""
        return self._staff_mutation(staff_id, query, {"input": {"ticketId": ticket_id}})

    def _staff_mutation(self, staff_id, query, variables):
        try:
            response = requests.post(f"{self.base_url}/graphql",
                json={"query": query, "variables": variables},
                headers=self._staff_headers(staff_id), timeout=30)
            data = response.json()
            if response.status_code == 200 and data.get("data"):
                return {"status": "success", "data": data["data"]}
            return {"status": "error", "error": data.get("errors", response.text)}
        except Exception as e:
            return {"status": "error", "error": str(e)}


class CustomerView(QWidget):
    """Customer support interface for chat-first conversational support."""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.current_ticket = None
        self.chat_history = []
        self.thinking_timer = None
        self.thinking_dots = 0
        self.first_customer_loaded = False
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Customer selection
        customer_group = QGroupBox("Customer Information")
        customer_layout = QFormLayout()
        
        self.customer_combo = QComboBox()
        self.customer_combo.addItems([
            "Alice Johnson (TechCorp Inc.)",
            "Bob Smith (StartupXYZ)", 
            "Carol Williams (Enterprise Solutions)",
            "David Brown (Digital Agency)",
            "Eva Martinez (Cloud Services LLC)"
        ])
        customer_layout.addRow("Select Customer:", self.customer_combo)
        customer_group.setLayout(customer_layout)
        
        # Chat interface
        chat_group = QGroupBox("AI Support Chat")
        chat_layout = QVBoxLayout()
        
        # Chat messages display
        self.chat_display = QListWidget()
        self.chat_display.setMaximumHeight(300)
        chat_layout.addWidget(self.chat_display)
        
        # Chat input
        chat_input_layout = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Type your message here... AI will help you and create a ticket if needed")
        self.send_chat_btn = QPushButton("Send")
        self.send_chat_btn.clicked.connect(self.send_chat_message)
        chat_input_layout.addWidget(self.chat_input)
        chat_input_layout.addWidget(self.send_chat_btn)
        
        chat_layout.addLayout(chat_input_layout)
        
        # Quick action buttons (removed "New Ticket" - AI creates tickets automatically)
        quick_layout = QHBoxLayout()
        quick_actions = ["Quick Issues", "Get Help", "History"]
        for action in quick_actions:
            btn = QPushButton(action)
            if action == "Quick Issues":
                btn.clicked.connect(self.show_quick_issues)
            elif action == "Get Help":
                btn.clicked.connect(self.get_help)
            elif action == "History":
                btn.clicked.connect(self.show_chat_history)
                btn.setStyleSheet("background-color: #6c757d; color: white;")
            quick_layout.addWidget(btn)
        
        chat_layout.addLayout(quick_layout)
        chat_group.setLayout(chat_layout)
        
        # Current ticket status (only shown when ticket exists)
        self.status_group = QGroupBox("Current Status")
        status_layout = QFormLayout()
        
        self.ticket_id_label = QLabel("-")
        self.ticket_status_label = QLabel("-")
        self.ticket_created_label = QLabel("-")
        
        status_layout.addRow("Ticket ID:", self.ticket_id_label)
        status_layout.addRow("Status:", self.ticket_status_label)
        status_layout.addRow("Created:", self.ticket_created_label)
        
        # Add close ticket button for customers
        self.close_ticket_btn = QPushButton("Close Ticket")
        self.close_ticket_btn.clicked.connect(self.close_customer_ticket)
        self.close_ticket_btn.setVisible(False)  # Only show when ticket exists
        status_layout.addRow(self.close_ticket_btn)
        
        self.status_group.setLayout(status_layout)
        self.status_group.setVisible(False)  # Initially hidden
        
        # Past Solutions section - show what AI solved for this customer
        solutions_group = QGroupBox("Past AI Solutions - What Was Solved")
        solutions_group.setStyleSheet("QGroupBox { font-weight: bold; color: #28a745; }")
        solutions_layout = QVBoxLayout()
        
        # Solutions display
        self.solutions_list = QListWidget()
        self.solutions_list.setMaximumHeight(150)
        solutions_layout.addWidget(self.solutions_list)
        
        solutions_group.setLayout(solutions_layout)
        
        # Add all to main layout
        layout.addWidget(customer_group)
        layout.addWidget(chat_group)
        layout.addWidget(self.status_group)
        layout.addWidget(solutions_group)
        
        self.setLayout(layout)
        
        # Add initial welcome message for first customer
        initial_customer = self.customer_combo.currentText()
        customer_first_name = initial_customer.split('(')[0].strip()
        welcome_msg = f"Welcome {customer_first_name}! I'm ready to help you with any issues. How can I assist you today?"
        self.add_chat_message("ai", welcome_msg)
        self.chat_history.append({"sender": "ai", "content": welcome_msg, "timestamp": datetime.now().isoformat()})
        
        # Set flag to skip first change event (since we just loaded initial state)
        self.first_customer_loaded = True
        
        # Connect customer change to fresh chat with a slight delay to avoid initial trigger
        QTimer.singleShot(100, lambda: self.customer_combo.currentIndexChanged.connect(self.on_customer_changed))
    
    def on_customer_changed(self, index):
        """Handle customer selection change - start fresh chat."""
        # Skip the first change event (initial load)
        if not self.first_customer_loaded:
            self.first_customer_loaded = True
            return
            
        if index < 0 or not hasattr(self, 'chat_display'):
            return
            
        # Get the customer name from the combo box
        customer_name = self.customer_combo.currentText()
            
        # Clear chat history
        self.chat_history = []
        self.chat_display.clear()
        
        # Clear current ticket
        self.current_ticket = None
        
        # Hide status group
        self.status_group.setVisible(False)
        
        # Clear solutions list 
        self.solutions_list.clear()
        
        # Get customer name for greeting
        customer_first_name = customer_name.split('(')[0].strip()
        
        # Show welcome message
        welcome_msg = f"Welcome {customer_first_name}! I'm ready to help you with any issues. How can I assist you today?"
        self.add_chat_message("ai", welcome_msg)
        self.chat_history.append({"sender": "ai", "content": welcome_msg, "timestamp": datetime.now().isoformat()})
    
    def add_sample_solutions(self):
        """Add sample past AI solutions for the customer."""
        # Empty for fresh start - solutions will be added as issues are resolved
        pass
    
    def add_to_solutions(self, issue, solution):
        """Add a new AI solution to the solutions list."""
        # Create a concise summary
        issue_summary = issue[:30] + "..." if len(issue) > 30 else issue
        solution_summary = solution[:50] + "..." if len(solution) > 50 else solution
        
        solution_text = f"{issue_summary} - AI: {solution_summary}"
        item = QListWidgetItem(solution_text)
        item.setForeground(QColor("#28a745"))
        self.solutions_list.addItem(item)
        self.solutions_list.scrollToBottom()
    
    def set_quick_issue(self, issue):
        """Set a quick issue template."""
        templates = {
            "Password Reset": "I need to reset my password. I can't access my account.",
            "Billing Question": "I have a question about my billing and need to update my payment method.",
            "Account Access": "I want to update my account settings and profile information.",
            "Technical Error": "I'm getting a 500 error when trying to upload files to my account.",
            "Delivery Inquiry": "How long does standard delivery take for my order?"
        }
        self.chat_input.setText(templates.get(issue, ""))

    def show_quick_issues(self):
        """Show quick issue options."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Quick Issues")
        layout = QVBoxLayout()
        
        quick_issues = ["Password Reset", "Billing Question", "Account Access", "Technical Error", "Delivery Inquiry"]
        for issue in quick_issues:
            btn = QPushButton(issue)
            btn.clicked.connect(lambda checked, text=issue: self.set_quick_issue(text))
            layout.addWidget(btn)
        
        dialog.setLayout(layout)
        dialog.exec()

    def get_help(self):
        """Get help information."""
        help_text = """
        AI Support Chat Help:
        ====================
        • Just start chatting - we'll handle your request automatically
        • Simple issues are resolved immediately by AI
        • Complex issues automatically create tickets for staff review
        • Click "Quick Issues" for common support topics
        • AI determines if a ticket is needed based on your issue
        """
        QMessageBox.information(self, "Help", help_text.strip())

    def show_chat_history(self):
        """Show chat history dialog with past conversations."""
        history_dialog = QDialog(self)
        history_dialog.setWindowTitle("Chat History")
        history_dialog.setMinimumSize(600, 400)
        
        layout = QVBoxLayout()
        
        # History display
        history_list_widget = QListWidget()
        
        if not self.chat_history:
            history_list_widget.addItem("No chat history yet. Start a conversation to see it here!")
        else:
            for msg in self.chat_history:
                sender = msg.get("sender", "unknown")
                content = msg.get("content", "")
                timestamp = msg.get("timestamp", "")
                
                # Format timestamp
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                    except:
                        time_str = timestamp
                else:
                    time_str = "Unknown time"
                
                # Format message
                item_text = f"[{time_str}] {sender}: {content}"
                item = QListWidgetItem(item_text)
                
                # Color-code by sender
                if sender == "user":
                    item.setForeground(QColor("#667eea"))
                elif sender == "ai":
                    item.setForeground(QColor("#28a745"))
                elif sender == "system":
                    item.setForeground(QColor("#6c757d"))
                elif sender == "staff":
                    item.setForeground(QColor("#dc3545"))
                
                history_list_widget.addItem(item)
        
        layout.addWidget(history_list_widget)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(history_dialog.accept)
        layout.addWidget(close_btn)
        
        history_dialog.setLayout(layout)
        history_dialog.exec()

    def send_chat_message(self):
        """Send a chat message and let AI handle it."""
        message = self.chat_input.text()
        if not message.strip():
            return
        
        # Add user message to chat
        self.add_chat_message("user", message)
        self.chat_history.append({"sender": "user", "content": message, "timestamp": datetime.now().isoformat()})
        self.chat_input.clear()
        
        # Check for simple greetings - respond instantly
        message_lower = message.lower().strip()
        greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"]
        
        if message_lower in greetings or any(message_lower.startswith(greeting) for greeting in greetings):
            # Get customer name from selection
            selected_customer = self.customer_combo.currentText()
            # Extract just the name (before the parentheses)
            customer_name = selected_customer.split('(')[0].strip()
            
            # Instant response for greetings with customer name
            greeting_responses = {
                "hi": f"Hello {customer_name}! Welcome to Shiva AI Support. How can I help you today?",
                "hello": f"Hello {customer_name}! Welcome to Shiva AI Support. How can I help you today?",
                "hey": f"Hey there {customer_name}! I'm here to help. What can I assist you with?",
                "good morning": f"Good morning {customer_name}! Thank you for contacting Shiva AI Support. How may I help you?",
                "good afternoon": f"Good afternoon {customer_name}! Thank you for contacting Shiva AI Support. How may I help you?",
                "good evening": f"Good evening {customer_name}! Thank you for contacting Shiva AI Support. How may I help you?",
                "greetings": f"Greetings {customer_name}! Welcome to Shiva AI Support. How can I help you today?"
            }
            response = greeting_responses.get(message_lower, f"Hello {customer_name}! How can I help you today?")
            self.add_chat_message("ai", response)
            self.chat_history.append({"sender": "ai", "content": response, "timestamp": datetime.now().isoformat()})
            return
        
        # For other messages, show thinking animation and process with AI immediately
        self.show_thinking_animation()
        self.process_message_with_ai(message)

    def add_chat_message(self, sender, content):
        """Add a message to the chat display."""
        item = QListWidgetItem(f"{sender}: {content}")
        if sender == "user":
            item.setForeground(QColor("#667eea"))
        elif sender == "ai":
            item.setForeground(QColor("#28a745"))
        elif sender == "system":
            item.setForeground(QColor("#6c757d"))
        elif sender == "staff":
            item.setForeground(QColor("#dc3545"))
        elif sender == "thinking":
            item.setForeground(QColor("#ffc107"))
        self.chat_display.addItem(item)
        self.chat_display.scrollToBottom()

    def show_thinking_animation(self):
        """Show animated dots like ChatGPT while AI is processing."""
        self.thinking_dots = 0
        self.thinking_item = QListWidgetItem(".")
        self.thinking_item.setForeground(QColor("#667eea"))
        self.thinking_item.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        self.chat_display.addItem(self.thinking_item)
        self.chat_display.scrollToBottom()
        
        # Start animation timer - faster for quick responses
        self.thinking_timer = QTimer()
        self.thinking_timer.timeout.connect(self.update_thinking_animation)
        self.thinking_timer.start(200)  # Faster updates for quicker feedback

    def update_thinking_animation(self):
        """Update the thinking animation dots - fast cycling."""
        self.thinking_dots = (self.thinking_dots + 1) % 3  # Cycle 0-2
        # Fast style: "." then ".." then "..." then back to "."
        dots = "." * (self.thinking_dots + 1)
        self.thinking_item.setText(dots)
        self.chat_display.scrollToBottom()

    def hide_thinking_animation(self):
        """Hide the thinking animation."""
        if self.thinking_timer:
            self.thinking_timer.stop()
            self.thinking_timer = None
        
        # Remove the thinking item
        if hasattr(self, 'thinking_item') and self.thinking_item:
            row = self.chat_display.row(self.thinking_item)
            self.chat_display.takeItem(row)
            self.thinking_item = None

    def process_message_with_ai(self, message):
        """Process user message with AI using real Groq with knowledge base."""
        # Call backend API for Groq analysis
        response = self.api_client.analyze_with_groq(message, self.chat_history)
        
        # Hide thinking animation
        self.hide_thinking_animation()
        
        if response["status"] == "success":
            # Parse the AI response from backend
            analysis = response.get("analysis", {})
            
            # A knowledge-base match is returned as a customer-ready solution.
            # Complex requests are escalated instead of showing an incomplete AI
            # answer followed by a second, conflicting message.
            ai_response = analysis.get("response", "")
            if analysis.get("needs_ticket"):
                self.create_ticket_with_summary(message, analysis.get("ticket"))
            else:
                ai_response = ai_response or "I couldn't find a solution. I'll create a ticket for our support team."
                self.add_chat_message("ai", ai_response)
                self.chat_history.append({"sender": "ai", "content": ai_response, "timestamp": datetime.now().isoformat()})
                self.add_to_solutions(message, ai_response)
            
        else:
            # Fallback to simple analysis if backend fails
            self.fallback_analysis(message)

    def fallback_analysis(self, message):
        """Fallback analysis when backend is unavailable."""
        message_lower = message.lower()
        resolved = False
        response = ""
        needs_ticket = False
        
        # Check for greetings first
        greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"]
        for greeting in greetings:
            if message_lower.strip() == greeting or message_lower.startswith(greeting):
                # Get customer name from selection
                selected_customer = self.customer_combo.currentText()
                # Extract just the name (before the parentheses)
                customer_name = selected_customer.split('(')[0].strip()
                
                greeting_responses = {
                    "hi": f"Hello {customer_name}! Welcome to Shiva AI Support. How can I help you today?",
                    "hello": f"Hello {customer_name}! Welcome to Shiva AI Support. How can I help you today?",
                    "hey": f"Hey there {customer_name}! I'm here to help. What can I assist you with?",
                    "good morning": f"Good morning {customer_name}! Thank you for contacting Shiva AI Support. How may I help you?",
                    "good afternoon": f"Good afternoon {customer_name}! Thank you for contacting Shiva AI Support. How may I help you?",
                    "good evening": f"Good evening {customer_name}! Thank you for contacting Shiva AI Support. How may I help you?",
                    "greetings": f"Greetings {customer_name}! Welcome to Shiva AI Support. How can I help you today?"
                }
                response = greeting_responses.get(greeting, f"Hello {customer_name}! How can I help you today?")
                self.add_chat_message("ai", response)
                self.chat_history.append({"sender": "ai", "content": response, "timestamp": datetime.now().isoformat()})
                return
        
        # Check for simple, resolvable issues
        simple_responses = {
            "password": "To reset your password, go to Settings > Security > Change Password. You'll receive an email with instructions.",
            "billing": "You can update your billing information in Settings > Subscription. We accept credit cards and PayPal.",
            "delivery": "Standard delivery takes 3-5 business days. Express delivery is available for 1-2 business days.",
            "account": "To access your account settings, go to Settings > Profile.",
            "login": "If you can't log in, use the password reset option in Settings > Security.",
            "payment": "You can pay using credit cards, PayPal, or other supported payment methods during checkout.",
            "checkout": "To complete checkout, add items to your cart and proceed to checkout.",
        }
        
        # Only clear investigation-heavy incidents are escalated in offline
        # fallback mode. Routine payment, account, and login questions should
        # still receive an AI/knowledge-base solution when the backend returns.
        complex_indicators = [
            "security breach", "account hacked", "unauthorized charge", "charged twice",
            "data loss", "production down", "server error", "outage", "500 error",
            "legal complaint", "fraud"
        ]
        
        # Check for generic/fallback response indicators - create ticket if response is too generic
        generic_response_indicators = [
            "check our knowledge base", "try refreshing", "clear browser cache", 
            "try different browser", "check internet connection", "based on what i know"
        ]
        
        # First check if it's a complex issue that needs a ticket
        for indicator in complex_indicators:
            if indicator in message_lower:
                needs_ticket = True
                break
        
        # If not complex, check if it's a simple resolvable issue
        if not needs_ticket:
            for keyword, simple_response in simple_responses.items():
                if keyword in message_lower:
                    response = simple_response
                    resolved = True
                    break
        
        if resolved:
            # Simple issue - AI resolves immediately without ticket
            self.add_chat_message("ai", response)
            self.chat_history.append({"sender": "ai", "content": response, "timestamp": datetime.now().isoformat()})
            # Add to solutions list
            self.add_to_solutions(message, response)
        elif needs_ticket:
            # Complex issue - AI automatically creates ticket with chat summary
            self.create_ticket_with_summary(message)
        else:
            # Use Groq API for better responses instead of generic fallback
            self.get_groq_response(message)

    def create_ticket_with_summary(self, issue_message, backend_ticket=None):
        """Create a ticket with chat summary for complex issues."""
        if backend_ticket:
            # The backend created the ticket, summary, and staff assignment.
            # Keep the GUI in sync rather than showing a simulated ticket.
            self.current_ticket = {
                "id": backend_ticket["id"],
                "customer_id": "gui_customer",
                "status": backend_ticket.get("status", "PENDING_STAFF"),
                "path": "STAFF",
                "assigned_staff_id": backend_ticket.get("assigned_staff_id"),
                "created_at": datetime.now().isoformat(),
                "messages": [],
            }
        elif not self.current_ticket:
            # Create new ticket
            self.current_ticket = {
                "id": f"ticket_{datetime.now().timestamp()}",
                "customer_id": "cust_001",
                "status": "PENDING_STAFF",
                "path": "STAFF",
                "assigned_staff_id": "staff_001",
                "created_at": datetime.now().isoformat(),
                "messages": []
            }
        
        # The backend already stored the message for a persistent ticket.
        if not backend_ticket:
            self.current_ticket["messages"].append({
                "id": f"msg_{datetime.now().timestamp()}",
                "sender": "customer",
                "content": issue_message,
                "created_at": datetime.now().isoformat()
            })
        
        # Generate chat summary using the conversation history
        summary = self.generate_chat_summary()
        
        # Add AI response about ticket creation
        # Keep this customer-facing response solution-focused. The full chat
        # summary is stored with the ticket for staff and is never echoed back.
        ai_response = (
            f"Ticket {self.current_ticket['id']} is now assigned to our support team. "
            "They will review the account details, investigate the issue, apply any "
            "needed correction, and update you here. Staff are responding to your issue; "
            "the usual response time is 3–5 minutes."
        )
        self.add_chat_message("ai", ai_response)
        self.chat_history.append({"sender": "ai", "content": ai_response, "timestamp": datetime.now().isoformat()})
        
        # Update status display
        self.update_status_display()

    def generate_chat_summary(self):
        """Generate a summary of the chat conversation."""
        if not self.chat_history:
            return "New support request"
        
        # Simple summary logic (in real system, use Groq for better summaries)
        recent_messages = self.chat_history[-5:]  # Last 5 messages
        summary_parts = []
        
        for msg in recent_messages:
            if msg["sender"] == "user":
                summary_parts.append(msg["content"][:50])  # First 50 chars
        
        if summary_parts:
            return " | ".join(summary_parts)
        else:
            return "Support conversation in progress"

    def get_groq_response(self, message):
        """Get response from Groq API with knowledge base integration."""
        try:
            response = self.api_client.get_groq_analysis(message, self.chat_history)
            
            if response.get("status") == "success":
                analysis = response.get("analysis", {})
                ai_response = analysis.get("response", "")
                needs_ticket = analysis.get("needs_ticket", False)
                message_type = analysis.get("message_type", "general_inquiry")
                
                if needs_ticket:
                    # SupportAI determined the answer is incomplete or unsafe.
                    self.create_ticket_with_summary(message)
                else:
                    # Good response from Groq - use it directly
                    self.add_chat_message("ai", ai_response)
                    self.chat_history.append({"sender": "ai", "content": ai_response, "timestamp": datetime.now().isoformat()})
                    self.add_to_solutions(message, ai_response)
            else:
                # API error - fall back to ticket creation
                self.create_ticket_with_summary(message)
                
        except Exception as e:
            # Error calling API - fall back to ticket creation
            print(f"Error calling Groq API: {e}")
            self.create_ticket_with_summary(message)

    def update_status_display(self):
        """Update the status display when a ticket exists."""
        if self.current_ticket:
            self.status_group.setVisible(True)
            self.ticket_id_label.setText(self.current_ticket["id"])
            self.ticket_status_label.setText(self.current_ticket["status"])
            self.ticket_created_label.setText(datetime.fromisoformat(self.current_ticket["created_at"]).strftime("%Y-%m-%d %H:%M:%S"))
            self.close_ticket_btn.setVisible(True)  # Show close button when ticket exists
        else:
            self.status_group.setVisible(False)
            self.close_ticket_btn.setVisible(False)  # Hide close button when no ticket
    
    def close_customer_ticket(self):
        """Allow customer to close their ticket."""
        if not self.current_ticket:
            QMessageBox.warning(self, "Warning", "No active ticket to close")
            return
        
        reply = QMessageBox.question(
            self, 
            "Close Ticket", 
            f"Are you sure you want to close ticket {self.current_ticket['id']}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.current_ticket["status"] = "CLOSED"
            self.update_status_display()
            self.chat_history.append({
                "sender": "system",
                "content": f"Ticket {self.current_ticket['id']} closed by customer",
                "timestamp": datetime.now().isoformat()
            })
            QMessageBox.information(self, "Success", "Ticket closed successfully")
    
    def create_ticket(self):
        """Create a new support ticket (legacy method)."""
        self.create_manual_ticket()
    
    def update_ticket_info(self):
        """Update ticket information display (legacy)."""
        self.update_status_display()
    
    def update_messages(self):
        """Update message thread display (legacy)."""
        # This is now handled by the chat display
        pass
    
    def update_workflow_step(self, step_index):
        """Update workflow step indicator."""
        for i, label in enumerate(self.step_labels):
            if i < step_index:
                label.setStyleSheet("background-color: #28a745; color: white; padding: 10px; border-radius: 5px;")
            elif i == step_index:
                label.setStyleSheet("background-color: #667eea; color: white; padding: 10px; border-radius: 5px;")
            else:
                label.setStyleSheet("background-color: #e9ecef; padding: 10px; border-radius: 5px;")
    
    def simulate_ai_routing(self):
        """Simulate AI routing process."""
        if not self.current_ticket:
            return
        
        message = self.current_ticket["messages"][0]["content"].lower()
        route = "support"
        
        # Check for greetings first
        greetings = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening"]
        if any(greeting in message for greeting in greetings):
            route = "greeting"
        elif any(keyword in message for keyword in ["error", "500", "crash", "technical"]):
            route = "code"
        elif any(keyword in message for keyword in ["password", "billing", "account", "delivery", "payment", "checkout"]):
            route = "support"
        else:
            route = "staff"
        
        self.current_ticket["path"] = route.upper()
        self.current_ticket["status"] = "IN_PROGRESS"
        
        self.update_ticket_info()
        self.update_workflow_step(1)
        
        # Simulate AI processing
        QTimer.singleShot(1500, lambda: self.simulate_ai_processing(route))
    
    def simulate_ai_processing(self, route):
        """Simulate AI processing with knowledge base content."""
        if not self.current_ticket:
            return
        
        response = ""
        auto_resolved = False
        confidence = 0.0
        
        if route == "greeting":
            # Handle greetings with a friendly response
            message = self.current_ticket["messages"][0]["content"].lower()
            if "hi" in message or "hello" in message:
                response = "Hello! Welcome to Shiva AI Support. How can I help you today?"
            elif "hey" in message:
                response = "Hey there! I'm here to help. What can I assist you with?"
            else:
                response = "Good day! Thank you for contacting Shiva AI Support. How may I help you?"
            confidence = 0.95
            auto_resolved = False  # Don't auto-resolve greetings, wait for actual query
        elif route == "support":
            message = self.current_ticket["messages"][0]["content"].lower()
            
            # Knowledge base content
            kb_responses = {
                "password": "To reset your password, go to Settings > Security > Change Password. You'll receive an email with instructions to reset your password.",
                "billing": "To update your billing information, go to Settings > Subscription. We accept credit cards, PayPal, and other supported payment methods.",
                "payment": "You can pay using credit cards, PayPal, or other supported payment methods during checkout.",
                "account": "To access your account settings, go to Settings > Profile. You can update your personal information and preferences there.",
                "login": "If you can't log in, use the password reset option. Go to Settings > Security > Change Password to reset your credentials.",
                "delivery": "Standard delivery takes 3-5 business days. Express delivery is available for 1-2 business days. International orders may be subject to customs duties.",
                "shipping": "Standard delivery takes 3-5 business days. Express delivery is available for 1-2 business days. International orders may be subject to customs duties.",
                "checkout": "To complete checkout, add items to your cart and proceed to checkout. You can pay using credit cards, PayPal, or other supported payment methods.",
                "cart": "Add items to your cart and proceed to checkout when ready. You can pay using credit cards, PayPal, or other supported payment methods.",
                "return": "To return an item, go to Orders > Select Order > Request Return. Follow the instructions to process your return.",
                "refund": "Refunds are processed within 5-7 business days after we receive your returned item. The refund will be credited to your original payment method."
            }
            
            # Find the best matching response from knowledge base
            for keyword, kb_response in kb_responses.items():
                if keyword in message:
                    response = kb_response
                    confidence = 0.85 + (0.1 * (keyword in ["password", "billing", "payment"]))  # Higher confidence for common queries
                    auto_resolved = confidence >= 0.85
                    break
            
            if not response:
                response = "I understand your concern. Based on our knowledge base, I don't have specific information for this query. Let me connect you with a support agent who can better assist you."
                confidence = 0.65
                auto_resolved = False
        else:
            response = "I've analyzed your technical issue. A fix recommendation has been generated and is awaiting staff review."
            confidence = 0.75
        
        ai_message = {
            "id": f"msg_{datetime.now().timestamp()}",
            "sender": f"{route}_ai" if route != "greeting" else "support_ai",
            "content": response,
            "created_at": datetime.now().isoformat()
        }
        
        self.current_ticket["messages"].append(ai_message)
        
        if auto_resolved:
            self.current_ticket["status"] = "RESOLVED_AUTO"
            self.update_workflow_step(3)
        else:
            self.current_ticket["status"] = "PENDING_STAFF"
            self.update_workflow_step(2)
        
        self.update_messages()
        self.update_ticket_info()
    
    def send_reply(self):
        """Send a customer reply."""
        reply = self.reply_input.text()
        if not reply.strip() or not self.current_ticket:
            QMessageBox.warning(self, "Warning", "Please enter a message and ensure you have an active ticket")
            return
        
        new_message = {
            "id": f"msg_{datetime.now().timestamp()}",
            "sender": "customer",
            "content": reply,
            "created_at": datetime.now().isoformat()
        }
        
        self.current_ticket["messages"].append(new_message)
        self.update_messages()
        self.reply_input.clear()


class AIRoutingView(QWidget):
    """AI routing analysis and visualization."""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Input section
        input_group = QGroupBox("Routing Analysis")
        input_layout = QFormLayout()
        
        self.routing_message = QTextEdit()
        self.routing_message.setPlaceholderText("Enter a message to analyze...")
        self.routing_message.setMaximumHeight(80)
        input_layout.addRow("Message:", self.routing_message)
        
        self.routing_attachments = QLineEdit()
        self.routing_attachments.setPlaceholderText("error.log, screenshot.png")
        input_layout.addRow("Attachments:", self.routing_attachments)
        
        # Scenario buttons
        scenario_layout = QHBoxLayout()
        scenarios = ["Technical Error", "Password Reset", "Billing Issue", "General Question", "Urgent Issue"]
        for scenario in scenarios:
            btn = QPushButton(scenario)
            btn.clicked.connect(lambda checked, text=scenario: self.set_scenario(text))
            scenario_layout.addWidget(btn)
        
        input_layout.addRow("Scenarios:", scenario_layout)
        
        self.analyze_btn = QPushButton("Analyze Routing")
        self.analyze_btn.clicked.connect(self.analyze_routing)
        input_layout.addRow(self.analyze_btn)
        
        input_group.setLayout(input_layout)
        
        # Results section
        results_group = QGroupBox("Analysis Results")
        results_layout = QFormLayout()
        
        self.tech_signal_label = QLabel("-")
        self.attachment_type_label = QLabel("-")
        self.kb_match_label = QLabel("-")
        self.confidence_label = QLabel("-")
        self.route_decision_label = QLabel("-")
        
        results_layout.addRow("Technical Signal:", self.tech_signal_label)
        results_layout.addRow("Attachment Type:", self.attachment_type_label)
        results_layout.addRow("KB Match:", self.kb_match_label)
        results_layout.addRow("Confidence:", self.confidence_label)
        results_layout.addRow("Route Decision:", self.route_decision_label)
        
        results_group.setLayout(results_layout)
        
        layout.addWidget(input_group)
        layout.addWidget(results_group)
        
        self.setLayout(layout)
    
    def set_scenario(self, scenario):
        """Set a test scenario."""
        templates = {
            "Technical Error": "I got a 500 Internal Server Error when uploading files",
            "Password Reset": "How do I reset my password?",
            "Billing Issue": "I need to update my billing information",
            "General Question": "What are your business hours?",
            "Urgent Issue": "Critical system down! Need immediate help!"
        }
        self.routing_message.setText(templates.get(scenario, ""))
    
    def analyze_routing(self):
        """Analyze message routing."""
        message = self.routing_message.toPlainText()
        if not message.strip():
            QMessageBox.warning(self, "Warning", "Please enter a message to analyze")
            return
        
        # Simulate analysis
        lower_message = message.lower()
        technical_signals = ["500", "404", "error", "crash", "broken", "traceback", "exception"]
        has_technical = any(signal in lower_message for signal in technical_signals)
        
        attachments = self.routing_attachments.text()
        has_technical_attachment = any(ext in attachments.lower() for ext in [".log", ".png"])
        
        # Update results
        self.tech_signal_label.setText("Yes" if has_technical or has_technical_attachment else "No")
        self.attachment_type_label.setText("Technical" if has_technical_attachment else "None")
        self.kb_match_label.setText(f"{0.7 + (0.2 * (not has_technical)):.2f}")
        self.confidence_label.setText(f"{0.8 + (0.15 * (has_technical or has_technical_attachment)):.2f}")
        
        # Determine route
        if has_technical or has_technical_attachment:
            route = "CODE"
        elif any(keyword in lower_message for keyword in ["password", "billing"]):
            route = "SUPPORT"
        else:
            route = "STAFF"
        
        self.route_decision_label.setText(route)
        self.route_decision_label.setStyleSheet("color: #667eea; font-weight: bold;")


class StaffView(QWidget):
    """Staff dashboard for ticket management."""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.selected_ticket_id = None
        self.init_ui()
    
    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Create a scroll area for the main content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        
        scroll_content = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Staff selection
        staff_group = QGroupBox("Staff Information")
        staff_group.setMaximumHeight(100)
        staff_layout = QFormLayout()
        
        self.staff_combo = QComboBox()
        self.staff_combo.addItems([
            "John Support (support_agent)",
            "Sarah Engineer (developer)",
            "Mike Lead (team_lead)"
        ])
        staff_layout.addRow("Select Staff:", self.staff_combo)
        self.staff_combo.currentIndexChanged.connect(self.refresh_assigned_tickets)
        staff_group.setLayout(staff_layout)
        
        # Ticket queue
        queue_group = QGroupBox("Ticket Queue")
        queue_group.setMaximumHeight(200)
        queue_layout = QVBoxLayout()
        
        self.ticket_table = QTableWidget()
        self.ticket_table.setColumnCount(4)
        self.ticket_table.setHorizontalHeaderLabels(["Ticket ID", "Customer", "Status", "Actions"])
        self.ticket_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        self.refresh_tickets_btn = QPushButton("Refresh Assigned Tickets")
        self.refresh_tickets_btn.clicked.connect(self.refresh_assigned_tickets)
        queue_layout.addWidget(self.refresh_tickets_btn)
        
        queue_layout.addWidget(self.ticket_table)
        queue_group.setLayout(queue_layout)
        
        # AI Resolved Tickets section - Enhanced "What was solved by AI"
        ai_resolved_group = QGroupBox("What Was Solved By AI")
        ai_resolved_group.setStyleSheet("QGroupBox { font-weight: bold; color: #28a745; }")
        ai_resolved_group.setMaximumHeight(400)
        ai_layout = QVBoxLayout()
        
        # Add comprehensive stats summary
        ai_stats_layout = QHBoxLayout()
        self.ai_resolved_count_label = QLabel("AI Resolved Today: 5")
        self.ai_resolved_count_label.setStyleSheet("font-weight: bold; color: #28a745; font-size: 14px;")
        self.ai_quality_label = QLabel("Solution Quality: 92%")
        self.ai_quality_label.setStyleSheet("font-weight: bold; color: #667eea; font-size: 14px;")
        self.ai_resolution_rate_label = QLabel("Resolution Rate: 92%")
        self.ai_resolution_rate_label.setStyleSheet("font-weight: bold; color: #17a2b8; font-size: 14px;")
        self.ai_time_saved_label = QLabel("Time Saved: ~4.2 hrs")
        self.ai_time_saved_label.setStyleSheet("font-weight: bold; color: #fd7e14; font-size: 14px;")
        ai_stats_layout.addWidget(self.ai_resolved_count_label)
        ai_stats_layout.addWidget(self.ai_quality_label)
        ai_stats_layout.addWidget(self.ai_resolution_rate_label)
        ai_stats_layout.addWidget(self.ai_time_saved_label)
        ai_stats_layout.addStretch()
        ai_layout.addLayout(ai_stats_layout)
        
        # Add filtering and controls
        ai_controls = QHBoxLayout()
        
        # Filter dropdown
        self.ai_filter_combo = QComboBox()
        self.ai_filter_combo.addItems(["All AI Resolutions", "Today Only", "This Week", "High Confidence Only", "Needs Review"])
        self.ai_filter_combo.setMinimumWidth(150)
        ai_controls.addWidget(QLabel("Filter:"))
        ai_controls.addWidget(self.ai_filter_combo)
        
        # Category filter
        self.ai_category_combo = QComboBox()
        self.ai_category_combo.addItems(["All Categories", "Password Reset", "Billing", "Account Access", "Technical Issues", "General Support"])
        self.ai_category_combo.setMinimumWidth(150)
        ai_controls.addWidget(QLabel("Category:"))
        ai_controls.addWidget(self.ai_category_combo)
        
        ai_controls.addStretch()
        
        # Action buttons
        self.refresh_ai_btn = QPushButton("Refresh")
        self.refresh_ai_btn.clicked.connect(self.refresh_ai_resolved_tickets)
        self.refresh_ai_btn.setStyleSheet("background-color: #28a745; color: white; padding: 5px;")
        
        self.export_ai_btn = QPushButton("Export Report")
        self.export_ai_btn.clicked.connect(self.export_ai_report)
        self.export_ai_btn.setStyleSheet("background-color: #667eea; color: white; padding: 5px;")
        
        ai_controls.addWidget(self.refresh_ai_btn)
        ai_controls.addWidget(self.export_ai_btn)
        ai_layout.addLayout(ai_controls)
        
        # Enhanced table with more columns
        self.ai_resolved_table = QTableWidget()
        self.ai_resolved_table.setColumnCount(7)
        self.ai_resolved_table.setHorizontalHeaderLabels([
            "Ticket ID", "Customer", "Issue Type", "Issue Solved", 
            "AI Response", "Feedback", "Resolved At"
        ])
        self.ai_resolved_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.ai_resolved_table.setMinimumHeight(150)
        
        # Make table sortable
        self.ai_resolved_table.setSortingEnabled(True)
        
        # Add sample AI-resolved tickets
        self.add_sample_ai_resolved_tickets()
        
        ai_layout.addWidget(self.ai_resolved_table)
        ai_resolved_group.setLayout(ai_layout)
        
        # Staff actions
        actions_group = QGroupBox("Staff Actions")
        actions_group.setMaximumHeight(150)
        actions_layout = QFormLayout()
        
        self.selected_ticket_label = QLabel("-")
        actions_layout.addRow("Selected Ticket:", self.selected_ticket_label)
        
        self.staff_response = QTextEdit()
        self.staff_response.setMaximumHeight(60)
        self.staff_response.setPlaceholderText("Type your response...")
        actions_layout.addRow("Response:", self.staff_response)
        
        action_buttons = QHBoxLayout()
        self.send_response_btn = QPushButton("Send Response")
        self.assign_btn = QPushButton("Refresh Queue")
        self.escalate_btn = QPushButton("View Summary")
        self.close_btn = QPushButton("Close Ticket")
        
        action_buttons.addWidget(self.send_response_btn)
        action_buttons.addWidget(self.assign_btn)
        action_buttons.addWidget(self.escalate_btn)
        action_buttons.addWidget(self.close_btn)
        
        actions_layout.addRow("Actions:", action_buttons)
        self.send_response_btn.clicked.connect(self.send_staff_response)
        self.close_btn.clicked.connect(self.close_selected_ticket)
        self.assign_btn.clicked.connect(self.refresh_assigned_tickets)
        actions_group.setLayout(actions_layout)
        
        # Performance metrics
        metrics_group = QGroupBox("Performance Metrics")
        metrics_group.setMaximumHeight(120)
        metrics_layout = QHBoxLayout()
        
        metrics = [
            ("Tickets Assigned", "12"),
            ("Resolved Today", "8"),
            ("AI Resolved Today", "15"),
            ("Satisfaction Rate", "95%")
        ]
        
        for label, value in metrics:
            metric_frame = QFrame()
            metric_frame.setFrameStyle(QFrame.Shape.StyledPanel)
            metric_layout_inner = QVBoxLayout()
            
            value_label = QLabel(value)
            value_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #667eea;")
            value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            name_label = QLabel(label)
            name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            metric_layout_inner.addWidget(value_label)
            metric_layout_inner.addWidget(name_label)
            metric_frame.setLayout(metric_layout_inner)
            metrics_layout.addWidget(metric_frame)
        
        metrics_group.setLayout(metrics_layout)
        
        layout.addWidget(staff_group)
        layout.addWidget(queue_group)
        layout.addWidget(ai_resolved_group)
        layout.addWidget(actions_group)
        layout.addWidget(metrics_group)
        layout.addStretch()
        
        scroll_content.setLayout(layout)
        scroll_area.setWidget(scroll_content)
        
        main_layout.addWidget(scroll_area)
        self.setLayout(main_layout)
        self.refresh_assigned_tickets()

    def current_staff_id(self):
        return ["staff_001", "staff_002", "staff_003"][self.staff_combo.currentIndex()]

    def refresh_assigned_tickets(self):
        result = self.api_client.get_assigned_tickets(self.current_staff_id())
        if result.get("status") != "success":
            return
        tickets = result["tickets"]
        self.ticket_table.setRowCount(len(tickets))
        for row, ticket in enumerate(tickets):
            self.ticket_table.setItem(row, 0, QTableWidgetItem(ticket["id"]))
            self.ticket_table.setItem(row, 1, QTableWidgetItem(ticket["customerId"]))
            self.ticket_table.setItem(row, 2, QTableWidgetItem(ticket["status"]))
            action_btn = QPushButton("Reply / Resolve")
            action_btn.clicked.connect(lambda checked, tid=ticket["id"]: self.select_ticket(tid))
            self.ticket_table.setCellWidget(row, 3, action_btn)
    
    def add_sample_tickets(self):
        """Add sample tickets to the queue."""
        sample_tickets = [
            ("ticket_abc123", "Alice Johnson", "PENDING_STAFF"),
            ("ticket_def456", "Bob Smith", "BUG"),
            ("ticket_ghi789", "Carol Williams", "IN_PROGRESS")
        ]
        
        self.ticket_table.setRowCount(len(sample_tickets))
        for row, (ticket_id, customer, status) in enumerate(sample_tickets):
            self.ticket_table.setItem(row, 0, QTableWidgetItem(ticket_id))
            self.ticket_table.setItem(row, 1, QTableWidgetItem(customer))
            
            status_item = QTableWidgetItem(status)
            if status == "PENDING_STAFF":
                status_item.setBackground(QColor("#ffc107"))
            elif status == "BUG":
                status_item.setBackground(QColor("#dc3545"))
            elif status == "IN_PROGRESS":
                status_item.setBackground(QColor("#667eea"))
            self.ticket_table.setItem(row, 2, status_item)
            
            # Add action button
            action_btn = QPushButton("View")
            action_btn.clicked.connect(lambda checked, tid=ticket_id: self.select_ticket(tid))
            self.ticket_table.setCellWidget(row, 3, action_btn)
    
    def add_sample_ai_resolved_tickets(self):
        """Add sample AI-resolved tickets showing what AI solved."""
        ai_resolved_tickets = [
            ("ticket_ai_001", "Alice Johnson", "Password Reset", "I need to reset my password", "Go to Settings > Security > Change Password. You'll receive an email with instructions.", "Helpful", "2024-01-15 09:30"),
            ("ticket_ai_002", "Bob Smith", "Billing", "How do I update my billing information?", "You can update your billing information in Settings > Subscription. We accept credit cards and PayPal.", "Helpful", "2024-01-15 10:15"),
            ("ticket_ai_003", "Carol Williams", "Delivery", "How long does standard delivery take?", "Standard delivery takes 3-5 business days. Express delivery is available for 1-2 business days.", "Partially Helpful", "2024-01-15 11:45"),
            ("ticket_ai_004", "David Brown", "Account Access", "I can't access my account settings", "To access your account settings, go to Settings > Profile. You can update your personal information and preferences there.", "Helpful", "2024-01-15 13:20"),
            ("ticket_ai_005", "Eva Martinez", "Payment", "What payment methods do you accept?", "You can pay using credit cards, PayPal, or other supported payment methods during checkout.", "Helpful", "2024-01-15 14:55"),
            ("ticket_ai_006", "Frank Wilson", "Technical Error", "Getting 404 error on login page", "Please check your internet connection and try again. If the issue persists, clear your browser cache and cookies.", "Helpful", "2024-01-15 15:30"),
            ("ticket_ai_007", "Grace Lee", "Subscription", "How do I cancel my subscription?", "To cancel your subscription, go to Settings > Subscription > Cancel Plan. You'll retain access until the end of your billing period.", "Partially Helpful", "2024-01-15 16:10"),
            ("ticket_ai_008", "Henry Davis", "Account Recovery", "Forgot my username", "Your username is typically your email address. You can recover it by using the 'Forgot Username' link on the login page.", "Helpful", "2024-01-15 17:45"),
            ("ticket_ai_009", "Ivy Chen", "Feature Request", "Can I add dark mode?", "Dark mode is available in Settings > Appearance. You can choose between light, dark, and system themes.", "Helpful", "2024-01-15 18:20"),
            ("ticket_ai_010", "Jack Miller", "Data Export", "How do I export my data?", "You can export your data from Settings > Data Management > Export. Choose your preferred format (CSV, JSON, or PDF).", "Helpful", "2024-01-15 19:00")
        ]
        
        # Update stats
        self.ai_resolved_count_label.setText(f"AI Resolved Today: {len(ai_resolved_tickets)}")
        
        # Calculate resolution rate (helpful + partially helpful / total)
        helpful_count = sum(1 for ticket in ai_resolved_tickets if ticket[5] in ["Helpful", "Partially Helpful"])
        resolution_rate = (helpful_count / len(ai_resolved_tickets)) * 100
        self.ai_quality_label.setText(f"Solution Quality: {resolution_rate:.0f}%")
        self.ai_resolution_rate_label.setText(f"Resolution Rate: {resolution_rate:.0f}%")
        
        # Estimate time saved (assuming 15 minutes per resolved ticket)
        time_saved_minutes = len(ai_resolved_tickets) * 15
        time_saved_hours = time_saved_minutes / 60
        self.ai_time_saved_label.setText(f"Time Saved: ~{time_saved_hours:.1f} hrs")
        
        self.ai_resolved_table.setRowCount(len(ai_resolved_tickets))
        for row, (ticket_id, customer, issue_type, issue_solved, ai_response, feedback, resolved_at) in enumerate(ai_resolved_tickets):
            self.ai_resolved_table.setItem(row, 0, QTableWidgetItem(ticket_id))
            self.ai_resolved_table.setItem(row, 1, QTableWidgetItem(customer))
            self.ai_resolved_table.setItem(row, 2, QTableWidgetItem(issue_type))
            
            # Truncate issue solved for display
            issue_display = issue_solved[:40] + "..." if len(issue_solved) > 40 else issue_solved
            self.ai_resolved_table.setItem(row, 3, QTableWidgetItem(issue_display))
            
            # Truncate AI response for display
            response_display = ai_response[:50] + "..." if len(ai_response) > 50 else ai_response
            self.ai_resolved_table.setItem(row, 4, QTableWidgetItem(response_display))
            
            # Color-code feedback
            feedback_item = QTableWidgetItem(feedback)
            if feedback == "Helpful":
                feedback_item.setBackground(QColor("#28a745"))
                feedback_item.setForeground(QColor("white"))
            elif feedback == "Partially Helpful":
                feedback_item.setBackground(QColor("#ffc107"))
            elif feedback == "Not Helpful":
                feedback_item.setBackground(QColor("#dc3545"))
                feedback_item.setForeground(QColor("white"))
            self.ai_resolved_table.setItem(row, 5, feedback_item)
            
            # Resolution time
            self.ai_resolved_table.setItem(row, 6, QTableWidgetItem(resolved_at))
    
    def refresh_ai_resolved_tickets(self):
        """Refresh AI resolved tickets from backend."""
        try:
            # Call backend to get AI resolved tickets
            response = self.api_client.get_ai_resolved_tickets()
            if response.get("status") == "success":
                tickets = response.get("tickets", [])
                self.update_ai_resolved_table(tickets)
                QMessageBox.information(self, "Success", f"Refreshed {len(tickets)} AI-resolved tickets")
            else:
                QMessageBox.warning(self, "Error", f"Failed to refresh: {response.get('error', 'Unknown error')}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to refresh: {str(e)}")
            # Fallback to sample data if backend fails
            self.add_sample_ai_resolved_tickets()
    
    def update_ai_resolved_table(self, tickets):
        """Update the AI resolved table with backend data."""
        # Update stats
        self.ai_resolved_count_label.setText(f"AI Resolved Today: {len(tickets)}")
        
        total_confidence = 0
        confidence_count = 0
        helpful_count = 0
        
        self.ai_resolved_table.setRowCount(len(tickets))
        for row, ticket in enumerate(tickets):
            self.ai_resolved_table.setItem(row, 0, QTableWidgetItem(ticket.get("id", "")))
            self.ai_resolved_table.setItem(row, 1, QTableWidgetItem(ticket.get("customer_id", "")))
            
            # Issue type (categorize based on content)
            issue_type = "General Support"
            messages = ticket.get("messages", [])
            customer_messages = [msg for msg in messages if msg.get("sender") == "customer"]
            if customer_messages:
                issue_content = customer_messages[0].get("content", "").lower()
                if "password" in issue_content:
                    issue_type = "Password Reset"
                elif "billing" in issue_content or "payment" in issue_content:
                    issue_type = "Billing"
                elif "account" in issue_content or "login" in issue_content:
                    issue_type = "Account Access"
                elif "error" in issue_content or "404" in issue_content or "500" in issue_content:
                    issue_type = "Technical Error"
                elif "delivery" in issue_content or "shipping" in issue_content:
                    issue_type = "Delivery"
            self.ai_resolved_table.setItem(row, 2, QTableWidgetItem(issue_type))
            
            # Extract issue from first customer message
            issue_solved = "Unknown issue"
            if customer_messages:
                issue_solved = customer_messages[0].get("content", "Unknown issue")[:40]
            self.ai_resolved_table.setItem(row, 3, QTableWidgetItem(issue_solved))
            
            # Extract AI response
            ai_response = "No AI response"
            ai_messages = [msg for msg in messages if msg.get("sender") in ["support_ai", "ai"]]
            if ai_messages:
                ai_response = ai_messages[-1].get("content", "No AI response")
            response_display = ai_response[:50] + "..." if len(ai_response) > 50 else ai_response
            self.ai_resolved_table.setItem(row, 4, QTableWidgetItem(response_display))
            
            # Confidence with color coding
            confidence = ticket.get("ai_resolution_confidence", 0)
            if confidence > 0:
                total_confidence += confidence
                confidence_count += 1
            
            confidence_item = QTableWidgetItem(f"{confidence:.0%}")
            if confidence >= 0.9:
                confidence_item.setBackground(QColor("#28a745"))
                confidence_item.setForeground(QColor("white"))
            elif confidence >= 0.8:
                confidence_item.setBackground(QColor("#667eea"))
                confidence_item.setForeground(QColor("white"))
            elif confidence >= 0.7:
                confidence_item.setBackground(QColor("#ffc107"))
            else:
                confidence_item.setBackground(QColor("#dc3545"))
                confidence_item.setForeground(QColor("white"))
            self.ai_resolved_table.setItem(row, 5, confidence_item)
            
            # Feedback
            feedback = ticket.get("ai_resolution_feedback", "No feedback")
            feedback_item = QTableWidgetItem(feedback)
            if feedback == "helpful":
                feedback_item.setBackground(QColor("#28a745"))
                feedback_item.setForeground(QColor("white"))
                helpful_count += 1
            elif feedback == "partially_helpful":
                feedback_item.setBackground(QColor("#ffc107"))
                helpful_count += 1
            elif feedback == "not_helpful":
                feedback_item.setBackground(QColor("#dc3545"))
                feedback_item.setForeground(QColor("white"))
            self.ai_resolved_table.setItem(row, 6, feedback_item)
            
            # Resolution time
            created_at = ticket.get("created_at", "")
            if created_at:
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    resolved_at = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    resolved_at = created_at[:16]
            else:
                resolved_at = "Unknown"
            self.ai_resolved_table.setItem(row, 7, QTableWidgetItem(resolved_at))
        
        # Update average confidence
        if confidence_count > 0:
            avg_confidence = total_confidence / confidence_count
            self.ai_avg_confidence_label.setText(f"Avg Confidence: {avg_confidence:.0%}")
        
        # Update resolution rate
        if len(tickets) > 0:
            resolution_rate = (helpful_count / len(tickets)) * 100
            self.ai_resolution_rate_label.setText(f"Resolution Rate: {resolution_rate:.0f}%")
        
        # Update time saved
        time_saved_hours = (len(tickets) * 15) / 60
        self.ai_time_saved_label.setText(f"Time Saved: ~{time_saved_hours:.1f} hrs")
    
    def select_ticket(self, ticket_id):
        """Select a ticket for actions."""
        self.selected_ticket_id = ticket_id
        self.selected_ticket_label.setText(ticket_id)

    def send_staff_response(self):
        content = self.staff_response.toPlainText().strip()
        if not self.selected_ticket_id or not content:
            QMessageBox.warning(self, "Reply required", "Select an assigned ticket and enter a reply.")
            return
        result = self.api_client.reply_to_ticket(self.current_staff_id(), self.selected_ticket_id, content)
        if result.get("status") == "success":
            self.staff_response.clear()
            QMessageBox.information(self, "Reply sent", "The customer chat was updated and an email notification was sent.")
        else:
            QMessageBox.warning(self, "Reply not sent", str(result.get("error")))

    def close_selected_ticket(self):
        if not self.selected_ticket_id:
            QMessageBox.warning(self, "Select a ticket", "Select an assigned ticket to close.")
            return
        result = self.api_client.close_staff_ticket(self.current_staff_id(), self.selected_ticket_id)
        if result.get("status") == "success":
            self.selected_ticket_id = None
            self.selected_ticket_label.setText("-")
            self.refresh_assigned_tickets()
            QMessageBox.information(self, "Ticket closed", "The ticket is closed.")
        else:
            QMessageBox.warning(self, "Ticket not closed", str(result.get("error")))
    
    def export_ai_report(self):
        """Export AI resolved tickets report to CSV."""
        try:
            # Get file path from user
            file_path, _ = QFileDialog.getSaveFileName(
                self, 
                "Export AI Report", 
                f"ai_resolved_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                "CSV Files (*.csv)"
            )
            
            if not file_path:
                return
            
            # Collect data from table
            report_data = []
            headers = []
            for col in range(self.ai_resolved_table.columnCount()):
                headers.append(self.ai_resolved_table.horizontalHeaderItem(col).text())
            report_data.append(headers)
            
            for row in range(self.ai_resolved_table.rowCount()):
                row_data = []
                for col in range(self.ai_resolved_table.columnCount()):
                    item = self.ai_resolved_table.item(row, col)
                    row_data.append(item.text() if item else "")
                report_data.append(row_data)
            
            # Write to CSV
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerows(report_data)
            
            QMessageBox.information(self, "Success", f"AI report exported successfully to {file_path}")
            
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to export report: {str(e)}")


class WorkflowTrackerView(QWidget):
    """Workflow tracking and visualization."""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Workflow visualization
        workflow_group = QGroupBox("Workflow Progress")
        workflow_layout = QHBoxLayout()
        
        self.workflow_steps = []
        steps = ["Created", "AI Routed", "AI Processed", "Response Sent", "Resolved"]
        for step in steps:
            step_frame = QFrame()
            step_frame.setFrameStyle(QFrame.Shape.StyledPanel)
            step_layout = QVBoxLayout()
            
            step_label = QLabel(step)
            step_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            step_label.setStyleSheet("font-weight: bold;")
            
            time_label = QLabel("-")
            time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            time_label.setStyleSheet("color: #6c757d; font-size: 10px;")
            
            step_layout.addWidget(step_label)
            step_layout.addWidget(time_label)
            step_frame.setLayout(step_layout)
            
            self.workflow_steps.append(step_frame)
            workflow_layout.addWidget(step_frame)
        
        workflow_group.setLayout(workflow_layout)
        
        # Workflow details
        details_group = QGroupBox("Workflow Details")
        details_layout = QFormLayout()
        
        self.workflow_ticket_id = QLabel("-")
        self.workflow_customer = QLabel("-")
        self.workflow_status = QLabel("-")
        self.workflow_path = QLabel("-")
        self.workflow_duration = QLabel("-")
        
        details_layout.addRow("Ticket ID:", self.workflow_ticket_id)
        details_layout.addRow("Customer:", self.workflow_customer)
        details_layout.addRow("Status:", self.workflow_status)
        details_layout.addRow("Path:", self.workflow_path)
        details_layout.addRow("Duration:", self.workflow_duration)
        
        details_group.setLayout(details_layout)
        
        # Event timeline
        timeline_group = QGroupBox("Event Timeline")
        timeline_layout = QVBoxLayout()
        
        self.timeline_list = QListWidget()
        self.timeline_list.addItem("Waiting for workflow to start...")
        timeline_layout.addWidget(self.timeline_list)
        
        timeline_group.setLayout(timeline_layout)
        
        # Control buttons
        controls_group = QGroupBox("Workflow Controls")
        controls_layout = QHBoxLayout()
        
        self.new_workflow_btn = QPushButton("Start New Workflow")
        self.reset_workflow_btn = QPushButton("Reset Workflow")
        self.export_workflow_btn = QPushButton("Export Workflow")
        
        controls_layout.addWidget(self.new_workflow_btn)
        controls_layout.addWidget(self.reset_workflow_btn)
        controls_layout.addWidget(self.export_workflow_btn)
        
        controls_group.setLayout(controls_layout)
        
        layout.addWidget(workflow_group)
        layout.addWidget(details_group)
        layout.addWidget(timeline_group)
        layout.addWidget(controls_group)
        
        self.setLayout(layout)


class DatabaseManagementView(QWidget):
    """Database management interface."""
    
    def __init__(self, api_client):
        super().__init__()
        self.api_client = api_client
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout()
        
        # Database operations
        operations_group = QGroupBox("Database Operations")
        operations_layout = QHBoxLayout()
        
        self.seed_btn = QPushButton("Seed Mock Data")
        self.seed_btn.clicked.connect(self.seed_database)
        
        self.clear_btn = QPushButton("Clear Mock Data")
        self.clear_btn.clicked.connect(self.clear_database)
        
        self.info_btn = QPushButton("Get Mock Data Info")
        self.info_btn.clicked.connect(self.get_mock_info)
        
        operations_layout.addWidget(self.seed_btn)
        operations_layout.addWidget(self.clear_btn)
        operations_layout.addWidget(self.info_btn)
        
        operations_group.setLayout(operations_layout)
        
        # Mock data display
        data_group = QGroupBox("Available Mock Data")
        data_layout = QVBoxLayout()
        
        self.customers_list = QListWidget()
        self.customers_list.setMaximumHeight(150)
        data_layout.addWidget(QLabel("Customers:"))
        data_layout.addWidget(self.customers_list)
        
        self.staff_list = QListWidget()
        self.staff_list.setMaximumHeight(150)
        data_layout.addWidget(QLabel("Staff:"))
        data_layout.addWidget(self.staff_list)
        
        data_group.setLayout(data_layout)
        
        # Operation results
        results_group = QGroupBox("Operation Results")
        results_layout = QVBoxLayout()
        
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMaximumHeight(150)
        results_layout.addWidget(self.results_text)
        
        results_group.setLayout(results_layout)
        
        layout.addWidget(operations_group)
        layout.addWidget(data_group)
        layout.addWidget(results_group)
        
        self.setLayout(layout)
        
        # Load initial data
        self.get_mock_info()
    
    def seed_database(self):
        """Seed the database with mock data."""
        result = self.api_client.seed_mock_database()
        self.results_text.setText(json.dumps(result, indent=2))
        self.get_mock_info()
    
    def clear_database(self):
        """Clear mock data from database."""
        result = self.api_client.clear_mock_database()
        self.results_text.setText(json.dumps(result, indent=2))
    
    def get_mock_info(self):
        """Get mock data information."""
        result = self.api_client.get_mock_data_info()
        self.results_text.setText(json.dumps(result, indent=2))
        
        if result.get("status") == "success" and "data" in result:
            self.customers_list.clear()
            for customer in result["data"]["customers"]:
                self.customers_list.addItem(f"{customer['id']}: {customer['name']} ({customer['email']})")
            
            self.staff_list.clear()
            for staff in result["data"]["staff"]:
                self.staff_list.addItem(f"{staff['id']}: {staff['name']} ({staff['email']})")


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.api_client = APIClient()
        self.init_ui()
        self.setup_status_bar()
        self.check_backend_health()
    
    def init_ui(self):
        self.setWindowTitle("Shiva Support Workflow GUI")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create central widget with tabs
        central_widget = QWidget()
        main_layout = QVBoxLayout()
        
        self.tab_widget = QTabWidget()
        
        # Add tabs
        self.customer_view = CustomerView(self.api_client)
        self.ai_routing_view = AIRoutingView()
        self.staff_view = StaffView(self.api_client)
        self.workflow_tracker = WorkflowTrackerView()
        self.database_view = DatabaseManagementView(self.api_client)
        
        self.tab_widget.addTab(self.customer_view, "Customer View")
        self.tab_widget.addTab(self.ai_routing_view, "AI Routing")
        self.tab_widget.addTab(self.staff_view, "Staff View")
        self.tab_widget.addTab(self.workflow_tracker, "Workflow Tracker")
        self.tab_widget.addTab(self.database_view, "Database Management")
        
        main_layout.addWidget(self.tab_widget)
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)
    
    def setup_status_bar(self):
        """Setup the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def check_backend_health(self):
        """Check backend health status."""
        def update_health():
            health = self.api_client.get_health()
            if health.get("status") == "healthy":
                self.status_bar.showMessage(f"Backend: Healthy (v{health.get('version', 'unknown')})")
            else:
                self.status_bar.showMessage("Backend: Disconnected or Error")
        
        # Check immediately and then every 30 seconds
        update_health()
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(update_health)
        self.health_timer.start(30000)


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
