-- get_queue() now retries no-match items after NO_MATCH_RECHECK_DAYS instead of leaving
-- them stuck forever: save_result()'s no-match branch already set next_attempt_at, but the
-- queue query only ever selected status = 'pending', so that retry timer was dead - a
-- no-match item never got status flipped back to 'pending', so it could never be selected
-- again. Fixed in app/nutrition_repository.py to select status in ('pending', 'no_match').
-- The pending-only partial index needs to cover 'no_match' too or it stops being used by
-- that query as soon as retries start happening.

drop index nutrition_lookups_pending_idx;

create index nutrition_lookups_queue_idx on nutrition_lookups (owner_user_id, next_attempt_at)
    where status in ('pending', 'no_match');
