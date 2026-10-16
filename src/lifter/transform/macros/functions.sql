-- SQL functions the models call, created in the target schema before the models are built
-- (on-run-start in dbt_project.yml).
{% macro create_functions() %}
-- least()/greatest() ignore NULL, so greatest(0, NULL) would be 0: guard explicitly.
create or replace function {{ target.schema }}.clamp_0_100(x numeric) returns numeric
language sql immutable
as $$ select case when x is null then null else least(100, greatest(0, x)) end $$;

-- Activity types that can be a CrossFit session (training, cardio on ergs, mobility). Other
-- activities (a bike commute, a walk) count in the load but never complete a session.
create or replace function {{ target.schema }}.is_session_activity(activity_type text) returns boolean
language sql immutable
as $$
    select coalesce(
        activity_type ~ '^(hiit|strength_training|stop_watch|indoor_cardio|indoor_rowing|indoor_cycling|fitness_equipment|cardio_training|training|crossfit|yoga|pilates|mobility|breathwork)$',
        false
    )
$$;
{% endmacro %}
