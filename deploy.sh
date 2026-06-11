#!/bin/bash
# deploy.sh — update investment_tracker locally AND push to Render
# Usage: ./deploy.sh "your commit message"
# Or just: ./deploy.sh   (uses a default message)

set -e

TRACKER_SRC="$HOME/Library/Application Support/Claude/local-agent-mode-sessions/5740b4a2-04a0-4d9c-9727-e34718598908/ad931bf2-4df1-467e-820c-b97d68885430/local_755b0622-1a4c-47ae-afb1-05007f4e744e/outputs/investment_tracker.py"
REPO_DIR="$HOME/alpa-tracker"
COMMIT_MSG="${1:-Update investment tracker}"

echo ""
echo "═══════════════════════════════════════"
echo "  Alpa Tracker — Deploy"
echo "═══════════════════════════════════════"

# 1. Copy latest tracker to repo
echo "📋 Copying tracker to repo..."
cp "$TRACKER_SRC" "$REPO_DIR/investment_tracker.py"

# 2. Git commit + push (triggers Render auto-deploy)
echo "🚀 Pushing to GitHub (Render will auto-deploy)..."
cd "$REPO_DIR"
git add investment_tracker.py
git commit -m "$COMMIT_MSG" || echo "   (nothing new to commit)"
git push

# 3. Kill any running local server
echo "🔄 Restarting local server on localhost:8765..."
pkill -f "investment_tracker.py" 2>/dev/null && echo "   ✓ Old server stopped" || echo "   (no server was running)"
sleep 1

# 4. Start fresh local server in background
nohup python3 "$REPO_DIR/investment_tracker.py" > /tmp/investment_tracker.log 2>&1 &
echo "   ✓ Local server started (PID $!)"
echo ""
echo "✅ Done!"
echo "   Local:  http://localhost:8765"
echo "   Render: auto-deploying from GitHub push"
echo ""
