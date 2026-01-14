# Configuración de Facebook y LinkedIn OAuth

Guía para configurar la publicación automática a Facebook Pages y LinkedIn Company Pages.

---

## Facebook Pages

### 1. Crear App en Facebook Developers

1. Ir a [developers.facebook.com](https://developers.facebook.com/)
2. Click en **My Apps** → **Create App**
3. Seleccionar **Business** como tipo de app
4. Nombre: `Ekimen Publisher` (o similar)
5. Crear la app

### 2. Configurar OAuth

1. En el dashboard de la app, ir a **App Settings** → **Basic**
2. Copiar:
   - **App ID** → `FACEBOOK_APP_ID`
   - **App Secret** → `FACEBOOK_APP_SECRET`

3. Ir a **Use Cases** → **Customize** → **Permissions**
4. Solicitar estos permisos:
   - `pages_manage_posts` - Publicar en páginas
   - `pages_read_engagement` - Leer métricas
   - `pages_show_list` - Listar páginas del usuario
   - `public_profile` - Info básica

### 3. Configurar Redirect URI

1. Ir a **Facebook Login** → **Settings**
2. En **Valid OAuth Redirect URIs** añadir:
   ```
   https://api.ekimen.ai/oauth/facebook/callback
   ```
3. Guardar cambios

### 4. Variables de Entorno

Añadir al `.env` del servidor:

```bash
FACEBOOK_APP_ID=tu-app-id-aqui
FACEBOOK_APP_SECRET=tu-app-secret-aqui
```

### 5. Business Verification (Producción)

Para usar en producción con usuarios externos:

1. Ir a **App Settings** → **Basic**
2. Completar **Business Verification**
3. Subir documentación de la empresa
4. Esperar aprobación (1-5 días)

### 6. Probar Conexión

```bash
# Verificar status
curl -H "Authorization: Bearer JWT" \
  https://api.ekimen.ai/oauth/facebook/status

# Respuesta esperada (no conectado)
{"connected": false}
```

---

## LinkedIn Company Pages

### 1. Crear App en LinkedIn Developers

1. Ir a [linkedin.com/developers](https://www.linkedin.com/developers/)
2. Click en **Create App**
3. Completar:
   - **App name**: `Ekimen Publisher`
   - **LinkedIn Page**: Seleccionar tu Company Page
   - **App logo**: Subir logo
4. Crear la app

### 2. Configurar OAuth

1. En el dashboard de la app, ir a **Auth**
2. Copiar:
   - **Client ID** → `LINKEDIN_CLIENT_ID`
   - **Client Secret** → `LINKEDIN_CLIENT_SECRET`

### 3. Solicitar Productos (Permisos)

1. Ir a **Products**
2. Solicitar acceso a:
   - **Share on LinkedIn** - Para publicar posts
   - **Sign In with LinkedIn using OpenID Connect** - Para autenticación

3. En **Auth** → **OAuth 2.0 scopes**, verificar que tienes:
   - `openid`
   - `profile`
   - `email`
   - `w_member_social`
   - `r_organization_social`
   - `w_organization_social`

### 4. Configurar Redirect URI

1. Ir a **Auth** → **OAuth 2.0 settings**
2. En **Authorized redirect URLs** añadir:
   ```
   https://api.ekimen.ai/oauth/linkedin/callback
   ```
3. Guardar

### 5. Variables de Entorno

Añadir al `.env` del servidor:

```bash
LINKEDIN_CLIENT_ID=tu-client-id-aqui
LINKEDIN_CLIENT_SECRET=tu-client-secret-aqui
```

### 6. Verificar Company Page Admin

El usuario que conecte debe ser **admin** de la Company Page en LinkedIn.

1. Ir a la Company Page en LinkedIn
2. Click en **Admin tools** → **Page admins**
3. Verificar que el usuario está listado

### 7. Probar Conexión

```bash
# Verificar status
curl -H "Authorization: Bearer JWT" \
  https://api.ekimen.ai/oauth/linkedin/status

# Respuesta esperada (no conectado)
{"connected": false}
```

---

## Endpoints Disponibles

### Facebook

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/oauth/facebook/start?token=JWT` | Inicia OAuth (popup) |
| GET | `/oauth/facebook/callback` | Callback automático |
| GET | `/oauth/facebook/status` | Estado de conexión |
| DELETE | `/oauth/facebook` | Desconectar cuenta |

### LinkedIn

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/oauth/linkedin/start?token=JWT` | Inicia OAuth (popup) |
| GET | `/oauth/linkedin/callback` | Callback automático |
| GET | `/oauth/linkedin/status` | Estado de conexión |
| DELETE | `/oauth/linkedin` | Desconectar cuenta |

---

## Frontend Integration

```javascript
// Abrir popup de conexión
function connectSocial(platform) {
    const jwt = getAuthToken();
    const popup = window.open(
        `https://api.ekimen.ai/oauth/${platform}/start?token=${jwt}`,
        `${platform}_oauth`,
        'width=600,height=700,scrollbars=yes'
    );
}

// Escuchar resultado
window.addEventListener('message', (event) => {
    const { type, error } = event.data;

    // Facebook
    if (type === 'facebook_oauth_success') {
        console.log('Facebook conectado:', event.data.page_name);
        refreshConnectionStatus();
    }
    if (type === 'facebook_oauth_error') {
        console.error('Facebook error:', error);
    }

    // LinkedIn
    if (type === 'linkedin_oauth_success') {
        console.log('LinkedIn conectado:', event.data.organization_name);
        refreshConnectionStatus();
    }
    if (type === 'linkedin_oauth_error') {
        console.error('LinkedIn error:', error);
    }
});

// Verificar estado de conexión
async function checkStatus(platform) {
    const res = await fetch(`/oauth/${platform}/status`, {
        headers: { 'Authorization': `Bearer ${jwt}` }
    });
    return res.json();
}

// Desconectar
async function disconnect(platform) {
    await fetch(`/oauth/${platform}`, {
        method: 'DELETE',
        headers: { 'Authorization': `Bearer ${jwt}` }
    });
}
```

---

## Troubleshooting

### Facebook

| Error | Causa | Solución |
|-------|-------|----------|
| "No Facebook Pages Found" | Usuario no es admin de ninguna página | Crear una Page o pedir acceso admin |
| "Invalid OAuth access token" | Token expirado | Reconectar cuenta |
| "App not authorized" | Permisos no aprobados | Completar Business Verification |

### LinkedIn

| Error | Causa | Solución |
|-------|-------|----------|
| "No Company Pages Found" | Usuario no es admin de Company Page | Pedir acceso admin en LinkedIn |
| "Invalid token" | Token expirado (60 días) | Reconectar cuenta |
| "Insufficient permissions" | Productos no activados | Solicitar productos en LinkedIn Developers |

---

## Checklist de Configuración

### Facebook
- [ ] App creada en Facebook Developers
- [ ] `FACEBOOK_APP_ID` en `.env`
- [ ] `FACEBOOK_APP_SECRET` en `.env`
- [ ] Redirect URI configurado
- [ ] Permisos solicitados
- [ ] Business Verification (para producción)

### LinkedIn
- [ ] App creada en LinkedIn Developers
- [ ] `LINKEDIN_CLIENT_ID` en `.env`
- [ ] `LINKEDIN_CLIENT_SECRET` en `.env`
- [ ] Redirect URI configurado
- [ ] Productos "Share on LinkedIn" activados
- [ ] Usuario es admin de Company Page
