"""MCP Tools for Semantika.

Exposes search, article management, and image tools via MCP protocol.
"""

from typing import Optional, List
from datetime import datetime, timedelta

from fastmcp import FastMCP

from utils.logger import get_logger
from utils.supabase_client import get_supabase_client

logger = get_logger("mcp.tools")


def create_mcp_server(company_id: str, client_name: str = "unknown") -> FastMCP:
    """
    Create an MCP server instance for a specific company.

    Args:
        company_id: The authenticated company's ID
        client_name: Name of the client for logging

    Returns:
        Configured FastMCP server instance
    """
    mcp = FastMCP(
        name="Semantika",
        instructions="""
        Semantika es una plataforma de gestión de contenidos para periodistas.

        Flujo típico:
        1. Usa 'search_news' para buscar noticias relevantes
        2. Usa 'create_article' para generar un artículo desde las noticias
        3. Usa 'update_article' para editar el contenido
        4. Usa 'publish_article' para publicar en WordPress/redes sociales

        Las imágenes se obtienen automáticamente de las fuentes originales.
        """
    )

    # Store company context
    mcp._company_id = company_id
    mcp._client_name = client_name

    # ==========================================
    # SEARCH TOOLS
    # ==========================================

    @mcp.tool()
    async def search_news(
        query: str,
        days_back: int = 7,
        limit: int = 20,
        categories: Optional[List[str]] = None,
        locations: Optional[List[str]] = None
    ) -> dict:
        """
        Busca noticias en el sistema.

        Args:
            query: Texto a buscar (búsqueda semántica)
            days_back: Días hacia atrás para buscar (default: 7)
            limit: Número máximo de resultados (default: 20, max: 50)
            categories: Filtrar por categorías (ej: ["política", "economía"])
            locations: Filtrar por ubicaciones (ej: ["Bilbao", "Bizkaia"])

        Returns:
            Lista de noticias con título, resumen, fuente y fecha
        """
        try:
            from utils.embedding_generator import generate_embedding

            supabase = get_supabase_client()

            # Generate embedding for semantic search
            query_embedding = generate_embedding(query)

            # Calculate date filter
            since_date = (datetime.utcnow() - timedelta(days=days_back)).isoformat()

            # Build the search query
            limit = min(limit, 50)  # Cap at 50

            # Use vector search function
            result = supabase.client.rpc(
                "search_context_units_hybrid",
                {
                    "query_embedding": query_embedding,
                    "query_text": query,
                    "p_company_id": company_id,
                    "p_limit": limit,
                    "p_since_date": since_date,
                    "p_include_pool": True
                }
            ).execute()

            if not result.data:
                return {"results": [], "total": 0, "query": query}

            # Format results
            formatted = []
            for item in result.data:
                formatted.append({
                    "id": item["id"],
                    "title": item.get("title", "Sin título"),
                    "summary": item.get("summary", "")[:500],
                    "source_name": item.get("source_metadata", {}).get("source_name", "Desconocido"),
                    "url": item.get("source_metadata", {}).get("url"),
                    "published_at": item.get("published_at"),
                    "category": item.get("category"),
                    "location": item.get("location"),
                    "relevance_score": round(item.get("score", 0), 3)
                })

            logger.info("mcp_search_news",
                company_id=company_id,
                query=query,
                results=len(formatted)
            )

            return {
                "results": formatted,
                "total": len(formatted),
                "query": query
            }

        except Exception as e:
            logger.error("mcp_search_news_error", error=str(e), company_id=company_id)
            return {"error": str(e), "results": [], "total": 0}

    @mcp.tool()
    async def get_news_detail(context_unit_id: str) -> dict:
        """
        Obtiene el detalle completo de una noticia.

        Args:
            context_unit_id: ID de la noticia (UUID)

        Returns:
            Noticia completa con todos los datos atómicos
        """
        try:
            supabase = get_supabase_client()

            # Get the context unit
            result = supabase.client.table("press_context_units")\
                .select("*")\
                .eq("id", context_unit_id)\
                .maybe_single()\
                .execute()

            if not result.data:
                return {"error": "Noticia no encontrada"}

            item = result.data

            # Verify access (own company or pool)
            pool_id = "99999999-9999-9999-9999-999999999999"
            if item["company_id"] != company_id and item["company_id"] != pool_id:
                return {"error": "No tienes acceso a esta noticia"}

            return {
                "id": item["id"],
                "title": item.get("title"),
                "summary": item.get("summary"),
                "atomic_statements": item.get("atomic_statements", []),
                "category": item.get("category"),
                "location": item.get("location"),
                "entities": item.get("entities", {}),
                "source_metadata": item.get("source_metadata", {}),
                "published_at": item.get("published_at"),
                "created_at": item.get("created_at"),
                "image_url": f"https://api.ekimen.ai/api/v1/context-units/{item['id']}/image"
            }

        except Exception as e:
            logger.error("mcp_get_news_detail_error", error=str(e))
            return {"error": str(e)}

    # ==========================================
    # ARTICLE TOOLS
    # ==========================================

    @mcp.tool()
    async def list_articles(
        estado: Optional[str] = None,
        limit: int = 20
    ) -> dict:
        """
        Lista los artículos de la empresa.

        Args:
            estado: Filtrar por estado (borrador, revision, aprobado, publicado)
            limit: Número máximo de resultados (default: 20)

        Returns:
            Lista de artículos con título, estado y fecha
        """
        try:
            supabase = get_supabase_client()

            query = supabase.client.table("press_articles")\
                .select("id, titulo, estado, category, created_at, updated_at, fecha_publicacion")\
                .eq("company_id", company_id)\
                .order("created_at", desc=True)\
                .limit(limit)

            if estado:
                query = query.eq("estado", estado)

            result = query.execute()

            # Format for readability
            articles = []
            for item in (result.data or []):
                articles.append({
                    "id": item["id"],
                    "titulo": item.get("titulo"),
                    "estado": item.get("estado"),
                    "category": item.get("category"),
                    "created_at": item.get("created_at"),
                    "fecha_publicacion": item.get("fecha_publicacion")
                })

            return {
                "articles": articles,
                "total": len(articles)
            }

        except Exception as e:
            logger.error("mcp_list_articles_error", error=str(e))
            return {"error": str(e), "articles": []}

    @mcp.tool()
    async def get_article(article_id: str) -> dict:
        """
        Obtiene el detalle completo de un artículo.

        Args:
            article_id: ID del artículo (UUID)

        Returns:
            Artículo completo con contenido, fuentes y estado
        """
        try:
            supabase = get_supabase_client()

            result = supabase.client.table("press_articles")\
                .select("*")\
                .eq("id", article_id)\
                .eq("company_id", company_id)\
                .maybe_single()\
                .execute()

            if not result.data:
                return {"error": "Artículo no encontrado"}

            article = result.data

            return {
                "id": article["id"],
                "titulo": article.get("titulo"),
                "slug": article.get("slug"),
                "contenido": article.get("contenido"),
                "excerpt": article.get("excerpt"),
                "estado": article.get("estado"),
                "category": article.get("category"),
                "tags": article.get("tags", []),
                "context_unit_ids": article.get("context_unit_ids", []),
                "imagen_url": article.get("imagen_url"),
                "created_at": article.get("created_at"),
                "updated_at": article.get("updated_at"),
                "fecha_publicacion": article.get("fecha_publicacion")
            }

        except Exception as e:
            logger.error("mcp_get_article_error", error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    async def create_article(
        title: str,
        content: str,
        context_unit_ids: List[str],
        category: Optional[str] = None,
        summary: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> dict:
        """
        Crea un nuevo artículo.

        Usa este tool después de redactar el contenido basándote en las noticias.

        Args:
            title: Título del artículo
            content: Contenido en Markdown
            context_unit_ids: IDs de las noticias usadas como fuente
            category: Categoría (política, economía, sociedad, cultura, deportes)
            summary: Resumen breve (se genera automáticamente si no se proporciona)
            tags: Lista de etiquetas

        Returns:
            Artículo creado en estado 'borrador'
        """
        try:
            import re
            from utils.embedding_generator import generate_embedding

            if not title or not content:
                return {"error": "Título y contenido son obligatorios"}

            if not context_unit_ids:
                return {"error": "Debes indicar al menos una noticia como fuente"}

            supabase = get_supabase_client()

            # Generate slug from title
            slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:80]

            # Auto-generate summary if not provided
            if not summary:
                summary = content[:300].rsplit(' ', 1)[0] + "..."

            # Generate embedding for related articles
            try:
                embedding_text = f"{title}. {content[:500]}"
                embedding = generate_embedding(embedding_text)
                embedding_str = f"[{','.join(map(str, embedding))}]"
            except Exception:
                embedding_str = None

            article_data = {
                "company_id": company_id,
                "titulo": title,
                "slug": slug,
                "contenido": content,
                "category": category,
                "estado": "borrador",
                "context_unit_ids": context_unit_ids,
                "tags": tags or [],
                "embedding": embedding_str,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            result = supabase.client.table("press_articles")\
                .insert(article_data)\
                .execute()

            if not result.data:
                return {"error": "Error al guardar el artículo"}

            article = result.data[0]

            logger.info("mcp_create_article",
                company_id=company_id,
                article_id=article["id"],
                title=title[:50],
                source_count=len(context_unit_ids)
            )

            return {
                "id": article["id"],
                "title": title,
                "slug": slug,
                "status": "borrador",
                "message": "Artículo creado correctamente. Usa update_article para editarlo o publish_article para publicarlo."
            }

        except Exception as e:
            logger.error("mcp_create_article_error", error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    async def update_article(
        article_id: str,
        titulo: Optional[str] = None,
        contenido: Optional[str] = None,
        excerpt: Optional[str] = None,
        estado: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None
    ) -> dict:
        """
        Actualiza un artículo existente.

        Args:
            article_id: ID del artículo a actualizar
            titulo: Nuevo título (opcional)
            contenido: Nuevo contenido en Markdown (opcional)
            excerpt: Nuevo resumen/extracto (opcional)
            estado: Nuevo estado: borrador, revision, aprobado (opcional)
            category: Nueva categoría (opcional)
            tags: Nuevas etiquetas (opcional)

        Returns:
            Confirmación de actualización
        """
        try:
            supabase = get_supabase_client()

            # Verify ownership
            existing = supabase.client.table("press_articles")\
                .select("id, estado")\
                .eq("id", article_id)\
                .eq("company_id", company_id)\
                .maybe_single()\
                .execute()

            if not existing.data:
                return {"error": "Artículo no encontrado"}

            # Can't edit published articles
            if existing.data["estado"] == "publicado":
                return {"error": "No se puede editar un artículo ya publicado"}

            # Build update
            update_data = {"updated_at": datetime.utcnow().isoformat()}

            if titulo is not None:
                update_data["titulo"] = titulo
            if contenido is not None:
                update_data["contenido"] = contenido
            if excerpt is not None:
                update_data["excerpt"] = excerpt
            if estado is not None:
                valid_states = ["borrador", "revision", "aprobado"]
                if estado not in valid_states:
                    return {"error": f"Estado inválido. Usa: {', '.join(valid_states)}"}
                update_data["estado"] = estado
            if category is not None:
                update_data["category"] = category
            if tags is not None:
                update_data["tags"] = tags

            result = supabase.client.table("press_articles")\
                .update(update_data)\
                .eq("id", article_id)\
                .execute()

            if not result.data:
                return {"error": "Error al actualizar"}

            logger.info("mcp_update_article",
                company_id=company_id,
                article_id=article_id,
                fields=list(update_data.keys())
            )

            return {
                "id": article_id,
                "updated_fields": list(update_data.keys()),
                "message": "Artículo actualizado correctamente"
            }

        except Exception as e:
            logger.error("mcp_update_article_error", error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    async def publish_article(
        article_id: str,
        platforms: Optional[List[str]] = None
    ) -> dict:
        """
        Publica un artículo en las plataformas configuradas.

        Args:
            article_id: ID del artículo a publicar
            platforms: Plataformas donde publicar (wordpress, twitter, linkedin). Si no se especifica, usa todas las configuradas.

        Returns:
            Resultado de la publicación con URLs
        """
        try:
            from publishers.publisher_factory import PublisherFactory

            supabase = get_supabase_client()

            # Get article
            article = supabase.client.table("press_articles")\
                .select("*")\
                .eq("id", article_id)\
                .eq("company_id", company_id)\
                .maybe_single()\
                .execute()

            if not article.data:
                return {"error": "Artículo no encontrado"}

            if article.data["estado"] not in ["revision", "aprobado"]:
                return {"error": "El artículo debe estar en estado 'revision' o 'aprobado' para publicar"}

            # Get publication targets
            query = supabase.client.table("press_publication_targets")\
                .select("*")\
                .eq("company_id", company_id)\
                .eq("is_active", True)

            if platforms:
                query = query.in_("platform_type", platforms)

            targets = query.execute()

            if not targets.data:
                return {"error": "No hay destinos de publicación configurados"}

            results = {}

            for target in targets.data:
                try:
                    publisher = PublisherFactory.create_publisher(
                        target["platform_type"],
                        target["base_url"],
                        target["credentials_encrypted"]
                    )

                    pub_result = await publisher.publish(article.data)
                    results[target["platform_type"]] = {
                        "success": pub_result.get("success", False),
                        "url": pub_result.get("url"),
                        "message": pub_result.get("message")
                    }
                except Exception as e:
                    results[target["platform_type"]] = {
                        "success": False,
                        "error": str(e)
                    }

            # Update article status
            supabase.client.table("press_articles")\
                .update({
                    "estado": "publicado",
                    "fecha_publicacion": datetime.utcnow().isoformat()
                })\
                .eq("id", article_id)\
                .execute()

            logger.info("mcp_publish_article",
                company_id=company_id,
                article_id=article_id,
                platforms=list(results.keys()),
                results=results
            )

            return {
                "article_id": article_id,
                "results": results,
                "message": "Publicación completada"
            }

        except Exception as e:
            logger.error("mcp_publish_article_error", error=str(e))
            return {"error": str(e)}

    # ==========================================
    # UTILITY TOOLS
    # ==========================================

    @mcp.tool()
    async def get_filter_options() -> dict:
        """
        Obtiene las opciones disponibles para filtrar búsquedas.

        Returns:
            Categorías y ubicaciones disponibles en el sistema
        """
        try:
            supabase = get_supabase_client()

            # Get categories
            cat_result = supabase.client.table("press_context_units")\
                .select("category")\
                .eq("company_id", company_id)\
                .not_.is_("category", "null")\
                .execute()

            categories = list(set(
                item["category"] for item in (cat_result.data or [])
                if item.get("category")
            ))

            # Get locations
            loc_result = supabase.client.table("press_context_units")\
                .select("location")\
                .eq("company_id", company_id)\
                .not_.is_("location", "null")\
                .execute()

            locations = list(set(
                item["location"] for item in (loc_result.data or [])
                if item.get("location")
            ))

            return {
                "categories": sorted(categories),
                "locations": sorted(locations),
                "statuses": ["draft", "review", "approved", "published"]
            }

        except Exception as e:
            logger.error("mcp_get_filter_options_error", error=str(e))
            return {"error": str(e)}

    @mcp.tool()
    async def get_company_stats() -> dict:
        """
        Obtiene estadísticas de uso de la empresa.

        Returns:
            Contadores de noticias, artículos y publicaciones
        """
        try:
            supabase = get_supabase_client()

            # Count context units
            cu_result = supabase.client.table("press_context_units")\
                .select("id", count="exact")\
                .eq("company_id", company_id)\
                .execute()

            # Count articles by estado
            articles_result = supabase.client.table("press_articles")\
                .select("estado")\
                .eq("company_id", company_id)\
                .execute()

            status_counts = {}
            for article in (articles_result.data or []):
                estado = article.get("estado", "desconocido")
                status_counts[estado] = status_counts.get(estado, 0) + 1

            return {
                "context_units_total": cu_result.count or 0,
                "articles_total": len(articles_result.data or []),
                "articles_by_status": status_counts
            }

        except Exception as e:
            logger.error("mcp_get_company_stats_error", error=str(e))
            return {"error": str(e)}

    return mcp
