-- Every model lands in the target schema itself (`analytics` once swapped in): readers query the
-- views by name through search_path analytics,public, so no `<schema>_<custom>` schemas.
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ target.schema }}
{%- endmacro %}
