CREATE TABLE IF NOT EXISTS user_global_stats
(
    user_id                   BIGINT PRIMARY KEY,

    -- Roulette
    roulette_money_gained     BIGINT DEFAULT 0,
    roulette_money_lost       BIGINT DEFAULT 0,
    roulette_bets_won         BIGINT DEFAULT 0,
    roulette_bets_lost        BIGINT DEFAULT 0,
    roulette_biggest_bet      BIGINT DEFAULT 0,

    -- Dice
    dice_money_gained         BIGINT DEFAULT 0,
    dice_money_lost           BIGINT DEFAULT 0,
    dice_bets_won             BIGINT DEFAULT 0,
    dice_bets_lost            BIGINT DEFAULT 0,
    dice_biggest_bet          BIGINT DEFAULT 0,

    -- Slots
    slots_money_gained        BIGINT DEFAULT 0,
    slots_money_lost          BIGINT DEFAULT 0,
    slots_bets_won            BIGINT DEFAULT 0,
    slots_bets_lost           BIGINT DEFAULT 0,
    slots_biggest_bet         BIGINT DEFAULT 0,

    -- Economy & Transfers
    money_given               BIGINT DEFAULT 0,
    money_received            BIGINT DEFAULT 0,
    biggest_money_gift        BIGINT DEFAULT 0,
    highest_money_accumulated BIGINT DEFAULT 0,
    money_spent               BIGINT DEFAULT 0,
    money_obtained            BIGINT DEFAULT 0,
    times_asked_allowance     BIGINT DEFAULT 0,
    money_from_allowance      BIGINT DEFAULT 0,
    biggest_allowance_streak  BIGINT DEFAULT 0,
    times_worked              BIGINT DEFAULT 0,
    money_from_work           BIGINT DEFAULT 0,
    times_switched_jobs       BIGINT DEFAULT 0,
    drops_claimed             BIGINT DEFAULT 0,
    money_from_drops          BIGINT DEFAULT 0,

    -- Crimes & Jail
    crimes_successful         BIGINT DEFAULT 0,
    times_gone_to_jail        BIGINT DEFAULT 0,
    crime_money_gained        BIGINT DEFAULT 0,
    crime_fines_paid          BIGINT DEFAULT 0,
    interest_money_gained     BIGINT DEFAULT 0,

    -- Mining & Crafting
    times_mined               BIGINT DEFAULT 0,
    times_drank               BIGINT DEFAULT 0,
    money_spent_drinking      BIGINT DEFAULT 0,
    energy_spent              BIGINT DEFAULT 0,
    basic_pickaxes_claimed    BIGINT DEFAULT 0,
    materials_mined           BIGINT DEFAULT 0,
    pickaxes_broken           BIGINT DEFAULT 0,
    items_crafted             BIGINT DEFAULT 0,
    items_sold                BIGINT DEFAULT 0,
    item_sales_money_gained   BIGINT DEFAULT 0
);