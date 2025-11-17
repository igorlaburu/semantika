# Guía de Integración - Autenticación Frontend

## Endpoints Disponibles

### 1. Registro de Usuario (Signup)

**Endpoint:** `POST /auth/signup`

**Request:**
```json
{
  "email": "usuario@empresa.com",
  "password": "password123",
  "company_name": "Mi Empresa SL",
  "cif": "B12345678",
  "tier": "starter"  // opcional: starter (default), pro, unlimited
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "expires_in": 3600,
  "user": {
    "id": "uuid",
    "email": "usuario@empresa.com",
    "created_at": "2025-11-17T..."
  },
  "company": {
    "id": "uuid",
    "name": "Mi Empresa SL",
    "cif": "B12345678",
    "tier": "starter"
  },
  "message": "Usuario y empresa creados correctamente. Revisa tu email para confirmar la cuenta."
}
```

**Errores:**
- `400`: CIF ya existe, tier inválido
- `500`: Error creando usuario o empresa

---

### 2. Login

**Endpoint:** `POST /auth/login`

**Request:**
```json
{
  "email": "usuario@empresa.com",
  "password": "password123"
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "expires_in": 3600,
  "user": {
    "id": "uuid",
    "email": "usuario@empresa.com",
    "created_at": "2025-11-17T..."
  }
}
```

**Errores:**
- `401`: Credenciales inválidas
- `403`: Usuario inactivo o sin empresa asignada

---

### 3. Obtener Usuario Actual

**Endpoint:** `GET /auth/user`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
  "id": "uuid",
  "email": "usuario@empresa.com",
  "name": "Nombre Usuario",
  "company_id": "uuid",
  "organization_id": "uuid",
  "role": "admin",
  "is_active": true
}
```

---

### 4. Refresh Token

**Endpoint:** `POST /auth/refresh`

**Request:**
```json
{
  "refresh_token": "eyJhbGc..."
}
```

**Response (200):**
```json
{
  "access_token": "eyJhbGc...",
  "refresh_token": "eyJhbGc...",
  "expires_in": 3600
}
```

---

### 5. Logout

**Endpoint:** `POST /auth/logout`

**Headers:**
```
Authorization: Bearer <access_token>
```

**Response (200):**
```json
{
  "success": true
}
```

---

## Flujo de Integración Frontend

### 1. Página de Registro (Signup)

```javascript
// signup.js / signup.vue / signup.tsx

async function handleSignup(formData) {
  try {
    const response = await fetch('http://localhost:8000/auth/signup', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        email: formData.email,
        password: formData.password,
        company_name: formData.companyName,
        cif: formData.cif,
        tier: formData.tier || 'starter'
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail);
    }

    const data = await response.json();

    // Guardar tokens en localStorage
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    localStorage.setItem('company', JSON.stringify(data.company));

    // Redirigir al dashboard
    window.location.href = '/dashboard';

  } catch (error) {
    alert('Error al registrarse: ' + error.message);
  }
}
```

**Formulario HTML:**
```html
<form onsubmit="handleSignup(event)">
  <input type="email" name="email" placeholder="Email" required />
  <input type="password" name="password" placeholder="Contraseña" required />
  <input type="text" name="companyName" placeholder="Nombre de la empresa" required />
  <input type="text" name="cif" placeholder="CIF" required />
  <select name="tier">
    <option value="starter">Starter</option>
    <option value="pro">Pro</option>
    <option value="unlimited">Unlimited</option>
  </select>
  <button type="submit">Registrarse</button>
</form>
```

---

### 2. Página de Login

```javascript
// login.js / login.vue / login.tsx

async function handleLogin(formData) {
  try {
    const response = await fetch('http://localhost:8000/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        email: formData.email,
        password: formData.password
      })
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail);
    }

    const data = await response.json();

    // Guardar tokens
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user', JSON.stringify(data.user));

    // Cargar info del usuario
    await loadUserInfo();

    // Redirigir
    window.location.href = '/dashboard';

  } catch (error) {
    alert('Error al iniciar sesión: ' + error.message);
  }
}

async function loadUserInfo() {
  const token = localStorage.getItem('access_token');

  const response = await fetch('http://localhost:8000/auth/user', {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });

  if (response.ok) {
    const user = await response.json();
    localStorage.setItem('user', JSON.stringify(user));
  }
}
```

---

### 3. Realizar Requests Autenticadas

```javascript
// api.js - Helper para requests autenticadas

async function apiRequest(url, options = {}) {
  const token = localStorage.getItem('access_token');

  const response = await fetch(url, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    }
  });

  // Si token expiró, intentar refresh
  if (response.status === 401) {
    const refreshed = await refreshToken();
    if (refreshed) {
      // Reintentar request con nuevo token
      return apiRequest(url, options);
    } else {
      // Redirect a login
      window.location.href = '/login';
      return null;
    }
  }

  return response;
}

async function refreshToken() {
  const refreshToken = localStorage.getItem('refresh_token');

  try {
    const response = await fetch('http://localhost:8000/auth/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken })
    });

    if (response.ok) {
      const data = await response.json();
      localStorage.setItem('access_token', data.access_token);
      localStorage.setItem('refresh_token', data.refresh_token);
      return true;
    }

    return false;
  } catch {
    return false;
  }
}

// Ejemplo de uso:
async function getContextUnits() {
  const response = await apiRequest('http://localhost:8000/api/v1/context-units');
  return response.json();
}
```

---

### 4. Logout

```javascript
async function handleLogout() {
  const token = localStorage.getItem('access_token');

  try {
    await fetch('http://localhost:8000/auth/logout', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });
  } finally {
    // Limpiar localStorage incluso si falla
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    localStorage.removeItem('company');

    window.location.href = '/login';
  }
}
```

---

### 5. Proteger Rutas (Route Guard)

**Vue Router:**
```javascript
router.beforeEach((to, from, next) => {
  const token = localStorage.getItem('access_token');
  const publicPages = ['/login', '/signup'];
  const authRequired = !publicPages.includes(to.path);

  if (authRequired && !token) {
    return next('/login');
  }

  next();
});
```

**React Router:**
```jsx
function PrivateRoute({ children }) {
  const token = localStorage.getItem('access_token');
  return token ? children : <Navigate to="/login" />;
}

// En routes:
<Route path="/dashboard" element={
  <PrivateRoute>
    <Dashboard />
  </PrivateRoute>
} />
```

---

## Notas Importantes

### Seguridad:
1. **Tokens en localStorage**: Seguros para aplicaciones web SPA
2. **HTTPS obligatorio** en producción
3. **Refresh tokens**: Expiran en ~7 días (configurable en Supabase)
4. **Access tokens**: Expiran en 1 hora

### Limitaciones Actuales:
- **1 usuario por empresa** (por ahora)
- **Solo nuevas empresas** pueden registrarse
- **CIF debe ser único**

### Row Level Security (RLS):
- Todos los endpoints filtran datos por `company_id` automáticamente
- Los usuarios solo ven datos de su empresa
- No es necesario filtrar por company_id en el frontend

---

## Testing Rápido

**Crear cuenta:**
```bash
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123",
    "company_name": "Test Company",
    "cif": "B12345678"
  }'
```

**Login:**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "password": "password123"
  }'
```

**Ver usuario:**
```bash
curl http://localhost:8000/auth/user \
  -H "Authorization: Bearer <access_token>"
```

---

## Próximos Pasos

1. Implementar formularios de signup/login en el frontend
2. Añadir interceptor HTTP para refresh automático de tokens
3. Persistir estado de autenticación (Vuex/Redux/Context)
4. UI para recuperación de contraseña (próximamente)
5. Soporte multi-usuario por empresa (próximamente)
