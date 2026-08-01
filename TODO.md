# Clerk Authentication Integration - Implementation Plan

## Phase 1: Backend Changes

### 1.1 Add Clerk JWT verification module
- [x] Create `backend/app/auth/clerk.py` - Clerk JWT validation using JWKS

### 1.2 Update backend config
- [x] Update `backend/app/config.py` - Add Clerk settings

### 1.3 Update backend middleware
- [x] Update `backend/app/api/middleware_auth.py` - Add Clerk JWT verification

### 1.4 Update auth routes
- [x] Update `backend/app/api/routes/auth.py` - Clerk-aware auth status

### 1.5 Add dependencies
- [x] Update `backend/requirements.txt` - Add pyjwt[crypto]

## Phase 2: Frontend Changes

### 2.1 Install Clerk SDK
- [x] Install `@clerk/nextjs` in frontend/oracle/apps/web

### 2.2 Update root layout
- [x] Update `frontend/oracle/apps/web/app/layout.tsx` - Wrap with ClerkProvider

### 2.3 Update middleware
- [x] Update `frontend/oracle/apps/web/middleware.ts` - Use clerkMiddleware

### 2.4 Update login page
- [x] Update `frontend/oracle/apps/web/app/login/page.tsx` - Use Clerk SignIn

### 2.5 Update signup page
- [x] Update `frontend/oracle/apps/web/app/signup/page.tsx` - Use Clerk SignUp

### 2.6 Update dashboard layout
- [x] Update `frontend/oracle/apps/web/app/dashboard/layout.tsx` - Add auth protection

### 2.7 Update nav-user component
- [x] Update `frontend/oracle/apps/web/components/nav-user.tsx` - Use Clerk UserButton

### 2.8 Update auth token helpers
- [x] Update `frontend/oracle/apps/web/lib/api/auth-token.ts` - Clerk token management

### 2.9 Update API client
- [x] Update `frontend/oracle/apps/web/lib/api/client.ts` - Use Clerk getToken()

### 2.10 Update settings page
- [x] Update `frontend/oracle/apps/web/app/dashboard/settings/page.tsx` - Clerk sign out

### 2.11 Update package.json
- [x] Update `frontend/oracle/apps/web/package.json` - @clerk/nextjs installed

## Phase 3: Environment Configuration
- [x] Create `.env.local` template with Clerk keys
- [x] Create `.env.example` template with Clerk keys
