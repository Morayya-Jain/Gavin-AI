#!/bin/bash

# AI Features Setup Script for Focus Tracker

clear
echo "═══════════════════════════════════════════════════════"
echo "🤖 AI Focus Tracker - AI Features Setup"
echo "═══════════════════════════════════════════════════════"
echo ""

# Check if .env already exists
if [ -f .env ]; then
    echo "⚠️  .env file already exists!"
    echo ""
    echo "Current content:"
    cat .env
    echo ""
    read -p "Do you want to update it? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled. Your .env file was not modified."
        exit 0
    fi
fi

echo ""
echo "📝 Let's set up your OpenAI API key"
echo ""
echo "To get your API key:"
echo "  1. Go to: https://platform.openai.com/api-keys"
echo "  2. Sign up or log in"
echo "  3. Click 'Create new secret key'"
echo "  4. Copy the key (starts with sk-...)"
echo ""
read -p "Paste your OpenAI API key here: " api_key

if [ -z "$api_key" ]; then
    echo ""
    echo "❌ No API key provided. Setup cancelled."
    exit 1
fi

# Validate key format
if [[ ! $api_key =~ ^sk- ]]; then
    echo ""
    echo "⚠️  Warning: API key doesn't start with 'sk-'"
    read -p "Continue anyway? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup cancelled."
        exit 1
    fi
fi

# Create .env file
echo "OPENAI_API_KEY=$api_key" > .env

echo ""
echo "═══════════════════════════════════════════════════════"
echo "✅ Setup Complete!"
echo "═══════════════════════════════════════════════════════"
echo ""
echo ".env file created with your API key"
echo ""
echo "🧪 Testing connection..."
echo ""

# Test the connection
python3 -c "
import sys
sys.path.insert(0, '.')
from ai.summariser import SessionSummariser

summariser = SessionSummariser()

if summariser.client:
    print('✅ OpenAI client initialized successfully!')
    print(f'   Model: {summariser.model}')
    print('')
    print('🎉 AI features are now active!')
    print('')
    print('Next steps:')
    print('  • Run: python3 main.py')
    print('  • Complete a study session')
    print('  • Get AI-powered insights in your report!')
else:
    print('❌ Failed to initialize OpenAI client')
    print('   Check your API key and try again')
" 2>&1

exit_code=$?

if [ $exit_code -ne 0 ]; then
    echo ""
    echo "⚠️  There was an issue testing the connection"
    echo "   Your .env file was created, but verify your API key"
fi

echo ""
echo "═══════════════════════════════════════════════════════"






