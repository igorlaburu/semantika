# Cambios WordPress ChromeNews - Solución Breadcrumbs

## Problema
WordPress en español (es_ES) tiene un bug donde los sufijos ordinales ingleses ("st", "nd", "rd", "th") aparecen incorrectamente en los breadcrumbs, mostrando "inicio / 2026 / rd / 03" en lugar de "inicio / 2026 / enero / 03".

## Solución
Modificamos el archivo de breadcrumbs para usar `date_i18n()` en lugar de `get_the_time(esc_html_x())` que causaba el bug de localización.

## Archivo modificado
- **Origen**: `/code/wp-content/themes/chromenews/lib/breadcrumb-trail/inc/breadcrumbs.php`
- **Backup**: `./breadcrumbs.php`

## Cambios realizados

### Líneas modificadas:
- **Línea 845**: `get_the_time(esc_html_x('F', 'monthly archives date format', 'chromenews'))` → `date_i18n('F', get_the_time('U'))`
- **Línea 905**: `get_the_time(esc_html_x('F', 'monthly archives date format', 'chromenews'))` → `date_i18n('F', get_the_time('U'))`
- **Línea 906**: `date('F', get_the_time('U'))` → `date_i18n('F', get_the_time('U'))`
- **Línea 1293**: `get_the_time(esc_html_x('F', 'monthly archives date format', 'chromenews'))` → `date_i18n('F', get_the_time('U', $post_id))`

## Cómo restaurar después de actualización del tema

1. **Restaurar archivo**:
   ```bash
   scp ./breadcrumbs.php ubuntu@api.ekimen.ai:/tmp/
   ssh ubuntu@api.ekimen.ai "sudo docker cp /tmp/breadcrumbs.php araba_press.1.qzhgvi9ztg5ftrydjmobkd63q:/code/wp-content/themes/chromenews/lib/breadcrumb-trail/inc/breadcrumbs.php"
   ```

2. **Limpiar cache**:
   ```bash
   ssh ubuntu@api.ekimen.ai "sudo docker exec araba_press.1.qzhgvi9ztg5ftrydjmobkd63q wp cache flush --allow-root --path=/code"
   ```

## Referencias
- WordPress Trac bug #22225: Ordinal suffixes not localized
- Problema identificado: 2026-01-03
- Solución implementada: 2026-01-03

## Resultado
✅ Breadcrumbs muestran correctamente: "Portada / 2026 / enero / 03"  
❌ En lugar de: "Portada / 2026 / rd / 03"