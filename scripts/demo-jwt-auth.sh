#!/bin/bash
# JWT Authentication Flow Demo
# This script demonstrates the complete JWT auth process

set -e

BASE_URL="${JAMARR_URL:-http://localhost:8111}"
COOKIES_FILE="/tmp/jamarr_cookies.txt"

echo "=========================================="
echo "JWT Authentication Flow Demo"
echo "=========================================="
echo ""

# Clean up old cookies
rm -f "$COOKIES_FILE"

# Step 1: Login
echo "Step 1: Login with username/password"
echo "--------------------------------------"
LOGIN_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username":"YOUR_USERNAME","password":"YOUR_PASSWORD"}' \
  -c "$COOKIES_FILE" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$LOGIN_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$LOGIN_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Login successful!"
    echo ""
    echo "Response:"
    echo "$RESPONSE_BODY" | jq '.'
    echo ""
    
    # Extract access token
    ACCESS_TOKEN=$(echo "$RESPONSE_BODY" | jq -r '.access_token')
    echo "Access Token (first 50 chars): ${ACCESS_TOKEN:0:50}..."
    echo ""
    
    # Show refresh cookie
    echo "Refresh Cookie:"
    grep jamarr_refresh "$COOKIES_FILE" || echo "  (cookie set in file)"
    echo ""
else
    echo "❌ Login failed with HTTP $HTTP_CODE"
    echo "$RESPONSE_BODY"
    exit 1
fi

# Step 2: Use access token to get user profile
echo "=========================================="
echo "Step 2: Get user profile with access token"
echo "--------------------------------------"
ME_RESPONSE=$(curl -s "$BASE_URL/api/auth/me" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$ME_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$ME_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Profile retrieved successfully!"
    echo ""
    echo "User Profile:"
    echo "$RESPONSE_BODY" | jq '.'
    echo ""
else
    echo "❌ Failed to get profile: HTTP $HTTP_CODE"
    echo "$RESPONSE_BODY"
fi

# Step 3: Refresh the access token
echo "=========================================="
echo "Step 3: Refresh access token"
echo "--------------------------------------"
REFRESH_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/refresh" \
  -b "$COOKIES_FILE" \
  -c "$COOKIES_FILE" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$REFRESH_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$REFRESH_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Token refreshed successfully!"
    echo ""
    echo "Response:"
    echo "$RESPONSE_BODY" | jq '.'
    echo ""
    
    # Extract new access token
    NEW_ACCESS_TOKEN=$(echo "$RESPONSE_BODY" | jq -r '.access_token')
    echo "New Access Token (first 50 chars): ${NEW_ACCESS_TOKEN:0:50}..."
    echo ""
    echo "Note: Old refresh token was revoked, new one set in cookie"
    echo ""
else
    echo "❌ Refresh failed: HTTP $HTTP_CODE"
    echo "$RESPONSE_BODY"
fi

# Step 4: Use new access token
echo "=========================================="
echo "Step 4: Use new access token"
echo "--------------------------------------"
ME_RESPONSE2=$(curl -s "$BASE_URL/api/auth/me" \
  -H "Authorization: Bearer $NEW_ACCESS_TOKEN" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$ME_RESPONSE2" | tail -n1)
RESPONSE_BODY=$(echo "$ME_RESPONSE2" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ New token works!"
    echo ""
    USERNAME=$(echo "$RESPONSE_BODY" | jq -r '.username')
    echo "Logged in as: $USERNAME"
    echo ""
else
    echo "❌ Failed: HTTP $HTTP_CODE"
fi

# Step 5: Try to reuse old refresh token (should fail)
echo "=========================================="
echo "Step 5: Test token rotation security"
echo "--------------------------------------"
echo "Attempting to reuse old (revoked) refresh token..."
echo "(This should fail with 401)"
echo ""

# We can't easily test this without saving the old cookie, so skip for now
echo "⏭️  Skipped (would require saving old cookie)"
echo ""

# Step 6: Logout
echo "=========================================="
echo "Step 6: Logout"
echo "--------------------------------------"
LOGOUT_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/logout" \
  -b "$COOKIES_FILE" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$LOGOUT_RESPONSE" | tail -n1)
RESPONSE_BODY=$(echo "$LOGOUT_RESPONSE" | head -n-1)

if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ Logged out successfully!"
    echo ""
    echo "Response:"
    echo "$RESPONSE_BODY" | jq '.'
    echo ""
else
    echo "❌ Logout failed: HTTP $HTTP_CODE"
fi

# Step 7: Verify logout (refresh should fail)
echo "=========================================="
echo "Step 7: Verify logout (refresh should fail)"
echo "--------------------------------------"
VERIFY_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/refresh" \
  -b "$COOKIES_FILE" \
  -w "\n%{http_code}")

HTTP_CODE=$(echo "$VERIFY_RESPONSE" | tail -n1)

if [ "$HTTP_CODE" = "401" ]; then
    echo "✅ Refresh correctly fails after logout!"
    echo ""
else
    echo "❌ Unexpected: refresh returned HTTP $HTTP_CODE"
fi

# Cleanup
rm -f "$COOKIES_FILE"

echo "=========================================="
echo "Demo Complete!"
echo "=========================================="
echo ""
echo "Summary of JWT Auth Flow:"
echo "1. Login → Get access token + refresh cookie"
echo "2. Use access token for API requests"
echo "3. Refresh → Get new access token (old refresh token revoked)"
echo "4. Logout → Revoke refresh token"
echo ""
