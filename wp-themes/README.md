# WordPress Themes para Araba.top

## ChromeNews Araba.top Child Theme

**Ubicación en servidor**: `/code/wp-content/themes/chromenews-arabatop/`

### Características
- ✅ **Child theme** de ChromeNews 
- ✅ **Breadcrumb fixes** para localización española
- ✅ **Screenshot** incluido para galería de temas
- ✅ **Protección** contra actualizaciones del tema padre

### Archivos principales
- `style.css` - Estilos y metadata del child theme
- `functions.php` - Funciones personalizadas mínimas
- `lib/breadcrumb-trail/inc/breadcrumbs.php` - **Breadcrumb fixes aplicados**
- `screenshot.png` - Preview del tema para WordPress admin

### Workflow de desarrollo

#### 1. Modificar en local
```bash
# Editar archivos en ./chromenews-arabatop/
code wp-themes/chromenews-arabatop/
```

#### 2. Subir cambios al servidor
```bash
# Comprimir tema modificado
cd wp-themes
tar -czf chromenews-arabatop.tar.gz chromenews-arabatop

# Subir al VPS
scp chromenews-arabatop.tar.gz semantika-vps:/tmp/

# Descomprimir en WordPress
ssh semantika-vps "sudo docker exec araba_press.1.qzhgvi9ztg5ftrydjmobkd63q rm -rf /code/wp-content/themes/chromenews-arabatop"
ssh semantika-vps "sudo docker cp /tmp/chromenews-arabatop.tar.gz araba_press.1.qzhgvi9ztg5ftrydjmobkd63q:/tmp/"
ssh semantika-vps "sudo docker exec araba_press.1.qzhgvi9ztg5ftrydjmobkd63q tar -xzf /tmp/chromenews-arabatop.tar.gz -C /code/wp-content/themes/"
```

#### 3. Limpiar cache
```bash
ssh semantika-vps "sudo docker exec araba_press.1.qzhgvi9ztg5ftrydjmobkd63q wp cache flush --allow-root --path=/code"
```

### Versionado con git
El child theme está incluido en este repositorio y versionado junto con semantika.

### Modificaciones aplicadas
- **Breadcrumb fixes**: Líneas 845, 905, 906, 1293 en `breadcrumbs.php`
- **Localización**: Usa `date_i18n()` en lugar de `get_the_time(esc_html_x())`
- **Bug fix**: Resuelve sufijos ordinales ("st", "nd", "rd") en español

### Próximas personalizaciones
- Añadir estilos personalizados en `style.css`
- Modificar funciones en `functions.php`
- Personalizar templates copiando desde tema padre

---
**Tema creado**: 2026-01-03  
**Última actualización**: 2026-01-03