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
# Also keep deploy.sh in sync
cp "${BASH_SOURCE[0]}" "$REPO_DIR/deploy.sh" 2>/dev/null || true

# 2. Git commit + push (triggers Render auto-deploy)
echo "🚀 Pushing to GitHub (Render will auto-deploy)..."
cd "$REPO_DIR"
git add investment_tracker.py deploy.sh
git commit -m "$COMMIT_MSG" || echo "   (nothing new to commit)"
git push

# 3. Kill any running local server (use -9 so it can't linger)
echo "🔄 Restarting local server on localhost:8765..."
pkill -9 -f "investment_tracker.py" 2>/dev/null && echo "   ✓ Old server killed" || echo "   (no server was running)"

# Wait until port 8765 is actually free (up to 10 seconds)
for i in $(seq 1 10); do
    lsof -i :8765 > /dev/null 2>&1 || break
    echo "   Waiting for port 8765 to free... ($i)"
    sleep 1
done
if lsof -i :8765 > /dev/null 2>&1; then
    echo "   ⚠ Port 8765 still in use — forcing kill by port"
    lsof -ti :8765 | xargs kill -9 2>/dev/null
    sleep 1
fi

# 4. Start fresh local server (-u = unbuffered so logs appear immediately)
nohup python3 -u "$REPO_DIR/investment_tracker.py" > /tmp/investment_tracker.log 2>&1 &
NEW_PID=$!
echo "   ✓ Local server started (PID $NEW_PID)"

# 5. Wait 3s then verify it's actually responding
sleep 3
if curl -s --max-time 2 http://localhost:8765 > /dev/null 2>&1; then
    echo "   ✅ Server verified responding on :8765"
else
    echo "   ⚠ Server not yet responding — log:"
    tail -20 /tmp/investment_tracker.log
fi

echo ""
echo "✅ Done!"
echo "   Local:  http://localhost:8765"
echo "   Render: auto-deploying from GitHub push"
echo ""
