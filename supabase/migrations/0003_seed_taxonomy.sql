insert into categories (slug, name, depth, path_slug, sort_order)
values
    ('grocery', 'Grocery & Everyday Retail', 0, 'grocery', 10),
    ('eating_out', 'Eating Out', 0, 'eating_out', 20),
    ('housing_utilities', 'Housing & Utilities', 0, 'housing_utilities', 30),
    ('transportation', 'Transportation', 0, 'transportation', 40),
    ('travel', 'Travel', 0, 'travel', 50),
    ('health', 'Health & Wellness', 0, 'health', 60),
    ('shopping', 'Shopping', 0, 'shopping', 70),
    ('entertainment', 'Entertainment', 0, 'entertainment', 80),
    ('education', 'Education', 0, 'education', 90),
    ('financial', 'Financial Expenses', 0, 'financial', 100),
    ('gifts_donations', 'Gifts & Donations', 0, 'gifts_donations', 110),
    ('miscellaneous', 'Miscellaneous', 0, 'miscellaneous', 120),
    ('uncategorized', 'Uncategorized', 0, 'uncategorized', 999)
on conflict (slug) do nothing;

with parents as (
    select id, slug from categories
),
seed(slug, parent_slug, name, depth, path_slug, sort_order) as (
    values
    ('grocery.food', 'grocery', 'Food & Beverages', 1, 'grocery.food', 10),
    ('grocery.household', 'grocery', 'Household Supplies', 1, 'grocery.household', 20),
    ('grocery.personal_care', 'grocery', 'Personal Care', 1, 'grocery.personal_care', 30),
    ('grocery.health_products', 'grocery', 'Health & Wellness Products', 1, 'grocery.health_products', 40),
    ('grocery.baby', 'grocery', 'Baby', 1, 'grocery.baby', 50),
    ('grocery.pet', 'grocery', 'Pet', 1, 'grocery.pet', 60),
    ('grocery.home_kitchen', 'grocery', 'Home & Kitchen', 1, 'grocery.home_kitchen', 70),
    ('grocery.electronics_office', 'grocery', 'Electronics & Office', 1, 'grocery.electronics_office', 80),
    ('grocery.clothing_accessories', 'grocery', 'Clothing & Accessories', 1, 'grocery.clothing_accessories', 90),
    ('grocery.seasonal_general', 'grocery', 'Seasonal & General Merchandise', 1, 'grocery.seasonal_general', 100),
    ('grocery.other', 'grocery', 'Other Everyday Retail', 1, 'grocery.other', 999),
    ('eating_out.restaurants', 'eating_out', 'Restaurants', 1, 'eating_out.restaurants', 10),
    ('eating_out.fast_food', 'eating_out', 'Fast Food', 1, 'eating_out.fast_food', 20),
    ('eating_out.cafes', 'eating_out', 'Cafes & Coffee Shops', 1, 'eating_out.cafes', 30),
    ('eating_out.delivery_takeout', 'eating_out', 'Delivery & Takeout', 1, 'eating_out.delivery_takeout', 40),
    ('eating_out.bars', 'eating_out', 'Bars & Alcohol Service', 1, 'eating_out.bars', 50),
    ('housing_utilities.rent_mortgage', 'housing_utilities', 'Rent & Mortgage', 1, 'housing_utilities.rent_mortgage', 10),
    ('housing_utilities.electricity', 'housing_utilities', 'Electricity', 1, 'housing_utilities.electricity', 20),
    ('housing_utilities.gas', 'housing_utilities', 'Gas', 1, 'housing_utilities.gas', 30),
    ('housing_utilities.water', 'housing_utilities', 'Water', 1, 'housing_utilities.water', 40),
    ('housing_utilities.internet_phone', 'housing_utilities', 'Internet & Phone', 1, 'housing_utilities.internet_phone', 50),
    ('housing_utilities.repairs', 'housing_utilities', 'Repairs & Maintenance', 1, 'housing_utilities.repairs', 60),
    ('transportation.fuel', 'transportation', 'Fuel', 1, 'transportation.fuel', 10),
    ('transportation.public_transit', 'transportation', 'Public Transit', 1, 'transportation.public_transit', 20),
    ('transportation.rideshare_taxi', 'transportation', 'Rideshare & Taxi', 1, 'transportation.rideshare_taxi', 30),
    ('transportation.parking_tolls', 'transportation', 'Parking & Tolls', 1, 'transportation.parking_tolls', 40),
    ('transportation.vehicle_maintenance', 'transportation', 'Vehicle Maintenance', 1, 'transportation.vehicle_maintenance', 50),
    ('travel.flights', 'travel', 'Flights', 1, 'travel.flights', 10),
    ('travel.lodging', 'travel', 'Lodging', 1, 'travel.lodging', 20),
    ('travel.car_rental', 'travel', 'Car Rental', 1, 'travel.car_rental', 30),
    ('travel.activities', 'travel', 'Travel Activities', 1, 'travel.activities', 40),
    ('health.services', 'health', 'Health Services', 1, 'health.services', 10),
    ('health.fitness', 'health', 'Fitness', 1, 'health.fitness', 20),
    ('health.therapy', 'health', 'Therapy & Mental Health', 1, 'health.therapy', 30),
    ('shopping.apparel', 'shopping', 'Apparel', 1, 'shopping.apparel', 10),
    ('shopping.electronics', 'shopping', 'Electronics', 1, 'shopping.electronics', 20),
    ('shopping.furniture', 'shopping', 'Furniture', 1, 'shopping.furniture', 30),
    ('entertainment.streaming', 'entertainment', 'Streaming & Subscriptions', 1, 'entertainment.streaming', 10),
    ('entertainment.events', 'entertainment', 'Events', 1, 'entertainment.events', 20),
    ('entertainment.games', 'entertainment', 'Games', 1, 'entertainment.games', 30),
    ('education.tuition', 'education', 'Tuition', 1, 'education.tuition', 10),
    ('education.books', 'education', 'Books & Materials', 1, 'education.books', 20),
    ('financial.bank_fees', 'financial', 'Bank Fees', 1, 'financial.bank_fees', 10),
    ('financial.interest', 'financial', 'Interest', 1, 'financial.interest', 20),
    ('gifts_donations.gifts', 'gifts_donations', 'Gifts', 1, 'gifts_donations.gifts', 10),
    ('gifts_donations.donations', 'gifts_donations', 'Donations', 1, 'gifts_donations.donations', 20)
)
insert into categories (slug, parent_id, name, depth, path_slug, sort_order)
select seed.slug, parents.id, seed.name, seed.depth, seed.path_slug, seed.sort_order
from seed
join parents on parents.slug = seed.parent_slug
on conflict (slug) do nothing;

with parents as (
    select id, slug from categories
),
seed(slug, parent_slug, name, depth, path_slug, sort_order) as (
    values
    ('grocery.food.produce', 'grocery.food', 'Fresh Produce', 2, 'grocery.food.produce', 10),
    ('grocery.food.dairy_eggs_alternatives', 'grocery.food', 'Dairy, Eggs & Alternatives', 2, 'grocery.food.dairy_eggs_alternatives', 20),
    ('grocery.food.meat_seafood_alternatives', 'grocery.food', 'Meat, Seafood & Alternatives', 2, 'grocery.food.meat_seafood_alternatives', 30),
    ('grocery.food.bakery', 'grocery.food', 'Bakery', 2, 'grocery.food.bakery', 40),
    ('grocery.food.grains_rice_pasta', 'grocery.food', 'Grains, Rice & Pasta', 2, 'grocery.food.grains_rice_pasta', 50),
    ('grocery.food.pulses_beans_lentils', 'grocery.food', 'Pulses, Beans & Lentils', 2, 'grocery.food.pulses_beans_lentils', 60),
    ('grocery.food.flour_baking', 'grocery.food', 'Flour & Baking Staples', 2, 'grocery.food.flour_baking', 70),
    ('grocery.food.breakfast', 'grocery.food', 'Breakfast Foods', 2, 'grocery.food.breakfast', 80),
    ('grocery.food.pantry_cooking', 'grocery.food', 'Pantry & Cooking Ingredients', 2, 'grocery.food.pantry_cooking', 90),
    ('grocery.food.condiments_spreads', 'grocery.food', 'Sauces, Condiments & Spreads', 2, 'grocery.food.condiments_spreads', 100),
    ('grocery.food.snacks', 'grocery.food', 'Snacks', 2, 'grocery.food.snacks', 110),
    ('grocery.food.sweets_desserts', 'grocery.food', 'Sweets & Desserts', 2, 'grocery.food.sweets_desserts', 120),
    ('grocery.food.prepared', 'grocery.food', 'Prepared & Ready-to-Eat Foods', 2, 'grocery.food.prepared', 130),
    ('grocery.food.beverages', 'grocery.food', 'Beverages', 2, 'grocery.food.beverages', 140),
    ('grocery.food.nutrition_sports', 'grocery.food', 'Nutrition & Sports Foods', 2, 'grocery.food.nutrition_sports', 150),
    ('grocery.food.other', 'grocery.food', 'Other Food & Beverages', 2, 'grocery.food.other', 999),
    ('grocery.household.cleaning', 'grocery.household', 'Cleaning Supplies', 2, 'grocery.household.cleaning', 10),
    ('grocery.household.laundry', 'grocery.household', 'Laundry Supplies', 2, 'grocery.household.laundry', 20),
    ('grocery.household.dishwashing', 'grocery.household', 'Dishwashing Supplies', 2, 'grocery.household.dishwashing', 30),
    ('grocery.household.paper_disposable', 'grocery.household', 'Paper & Disposable Products', 2, 'grocery.household.paper_disposable', 40),
    ('grocery.household.garbage_storage', 'grocery.household', 'Garbage & Food Storage', 2, 'grocery.household.garbage_storage', 50),
    ('grocery.household.maintenance', 'grocery.household', 'Household Maintenance', 2, 'grocery.household.maintenance', 60),
    ('grocery.household.pest_control', 'grocery.household', 'Pest Control', 2, 'grocery.household.pest_control', 70),
    ('grocery.household.air_care', 'grocery.household', 'Air Care', 2, 'grocery.household.air_care', 80),
    ('grocery.personal_care.bath_body', 'grocery.personal_care', 'Bath & Body', 2, 'grocery.personal_care.bath_body', 10),
    ('grocery.personal_care.hair', 'grocery.personal_care', 'Hair Care', 2, 'grocery.personal_care.hair', 20),
    ('grocery.personal_care.oral', 'grocery.personal_care', 'Oral Care', 2, 'grocery.personal_care.oral', 30),
    ('grocery.personal_care.skin', 'grocery.personal_care', 'Skin Care', 2, 'grocery.personal_care.skin', 40),
    ('grocery.health_products.otc_medicine', 'grocery.health_products', 'Over-the-Counter Medicine', 2, 'grocery.health_products.otc_medicine', 10),
    ('grocery.health_products.first_aid', 'grocery.health_products', 'First Aid', 2, 'grocery.health_products.first_aid', 20),
    ('grocery.health_products.vitamins_supplements', 'grocery.health_products', 'Vitamins & Supplements', 2, 'grocery.health_products.vitamins_supplements', 30),
    ('grocery.baby.food_formula', 'grocery.baby', 'Baby Food & Formula', 2, 'grocery.baby.food_formula', 10),
    ('grocery.baby.diapers', 'grocery.baby', 'Diapers', 2, 'grocery.baby.diapers', 20),
    ('grocery.pet.food', 'grocery.pet', 'Pet Food', 2, 'grocery.pet.food', 10),
    ('grocery.pet.treats', 'grocery.pet', 'Treats', 2, 'grocery.pet.treats', 20),
    ('grocery.home_kitchen.cookware', 'grocery.home_kitchen', 'Cookware', 2, 'grocery.home_kitchen.cookware', 10),
    ('grocery.home_kitchen.kitchen_tools', 'grocery.home_kitchen', 'Kitchen Tools', 2, 'grocery.home_kitchen.kitchen_tools', 20),
    ('grocery.electronics_office.consumer_electronics', 'grocery.electronics_office', 'Consumer Electronics', 2, 'grocery.electronics_office.consumer_electronics', 10),
    ('grocery.electronics_office.stationery', 'grocery.electronics_office', 'Stationery', 2, 'grocery.electronics_office.stationery', 20),
    ('grocery.clothing_accessories.mens', 'grocery.clothing_accessories', 'Men''s Clothing', 2, 'grocery.clothing_accessories.mens', 10),
    ('grocery.clothing_accessories.womens', 'grocery.clothing_accessories', 'Women''s Clothing', 2, 'grocery.clothing_accessories.womens', 20),
    ('grocery.seasonal_general.holiday', 'grocery.seasonal_general', 'Holiday Products', 2, 'grocery.seasonal_general.holiday', 10),
    ('grocery.seasonal_general.sports_recreation_goods', 'grocery.seasonal_general', 'Sports & Recreation Goods', 2, 'grocery.seasonal_general.sports_recreation_goods', 20)
)
insert into categories (slug, parent_id, name, depth, path_slug, sort_order)
select seed.slug, parents.id, seed.name, seed.depth, seed.path_slug, seed.sort_order
from seed
join parents on parents.slug = seed.parent_slug
on conflict (slug) do nothing;

with parents as (
    select id, slug from categories
),
seed(slug, parent_slug, name, depth, path_slug, sort_order) as (
    values
    ('grocery.food.produce.fruit', 'grocery.food.produce', 'Fruit', 3, 'grocery.food.produce.fruit', 10),
    ('grocery.food.produce.vegetables', 'grocery.food.produce', 'Vegetables', 3, 'grocery.food.produce.vegetables', 20),
    ('grocery.food.produce.herbs', 'grocery.food.produce', 'Fresh Herbs', 3, 'grocery.food.produce.herbs', 30),
    ('grocery.food.produce.mushrooms', 'grocery.food.produce', 'Mushrooms', 3, 'grocery.food.produce.mushrooms', 40),
    ('grocery.food.produce.salad_kits', 'grocery.food.produce', 'Salad Kits', 3, 'grocery.food.produce.salad_kits', 50),
    ('grocery.food.dairy_eggs_alternatives.milk', 'grocery.food.dairy_eggs_alternatives', 'Milk', 3, 'grocery.food.dairy_eggs_alternatives.milk', 10),
    ('grocery.food.dairy_eggs_alternatives.plant_milk', 'grocery.food.dairy_eggs_alternatives', 'Plant-Based Milk', 3, 'grocery.food.dairy_eggs_alternatives.plant_milk', 20),
    ('grocery.food.dairy_eggs_alternatives.yogurt', 'grocery.food.dairy_eggs_alternatives', 'Yogurt', 3, 'grocery.food.dairy_eggs_alternatives.yogurt', 30),
    ('grocery.food.dairy_eggs_alternatives.cheese', 'grocery.food.dairy_eggs_alternatives', 'Cheese', 3, 'grocery.food.dairy_eggs_alternatives.cheese', 40),
    ('grocery.food.dairy_eggs_alternatives.eggs', 'grocery.food.dairy_eggs_alternatives', 'Eggs & Egg Products', 3, 'grocery.food.dairy_eggs_alternatives.eggs', 50),
    ('grocery.food.grains_rice_pasta.rice', 'grocery.food.grains_rice_pasta', 'Rice', 3, 'grocery.food.grains_rice_pasta.rice', 10),
    ('grocery.food.grains_rice_pasta.pasta', 'grocery.food.grains_rice_pasta', 'Pasta', 3, 'grocery.food.grains_rice_pasta.pasta', 20),
    ('grocery.food.pulses_beans_lentils.lentils', 'grocery.food.pulses_beans_lentils', 'Lentils', 3, 'grocery.food.pulses_beans_lentils.lentils', 10),
    ('grocery.food.pulses_beans_lentils.beans', 'grocery.food.pulses_beans_lentils', 'Beans', 3, 'grocery.food.pulses_beans_lentils.beans', 20),
    ('grocery.food.pulses_beans_lentils.chickpeas', 'grocery.food.pulses_beans_lentils', 'Chickpeas', 3, 'grocery.food.pulses_beans_lentils.chickpeas', 30),
    ('grocery.food.pantry_cooking.spices_seasonings', 'grocery.food.pantry_cooking', 'Spices, Seasonings & Masalas', 3, 'grocery.food.pantry_cooking.spices_seasonings', 10),
    ('grocery.food.snacks.nuts', 'grocery.food.snacks', 'Nuts', 3, 'grocery.food.snacks.nuts', 10),
    ('grocery.food.snacks.protein_bars', 'grocery.food.snacks', 'Protein Bars', 3, 'grocery.food.snacks.protein_bars', 20),
    ('grocery.food.snacks.indian_snacks', 'grocery.food.snacks', 'Savoury Indian Snacks', 3, 'grocery.food.snacks.indian_snacks', 30),
    ('grocery.food.sweets_desserts.chocolate', 'grocery.food.sweets_desserts', 'Chocolate', 3, 'grocery.food.sweets_desserts.chocolate', 10)
)
insert into categories (slug, parent_id, name, depth, path_slug, sort_order)
select seed.slug, parents.id, seed.name, seed.depth, seed.path_slug, seed.sort_order
from seed
join parents on parents.slug = seed.parent_slug
on conflict (slug) do nothing;

with parents as (
    select id, slug from categories
),
seed(slug, parent_slug, name, depth, path_slug, sort_order) as (
    values
    ('grocery.food.produce.fruit.apples', 'grocery.food.produce.fruit', 'Apples', 4, 'grocery.food.produce.fruit.apples', 10),
    ('grocery.food.produce.fruit.bananas', 'grocery.food.produce.fruit', 'Bananas', 4, 'grocery.food.produce.fruit.bananas', 20),
    ('grocery.food.produce.fruit.citrus', 'grocery.food.produce.fruit', 'Citrus Fruit', 4, 'grocery.food.produce.fruit.citrus', 30),
    ('grocery.food.produce.fruit.berries', 'grocery.food.produce.fruit', 'Berries', 4, 'grocery.food.produce.fruit.berries', 40),
    ('grocery.food.produce.fruit.grapes', 'grocery.food.produce.fruit', 'Grapes', 4, 'grocery.food.produce.fruit.grapes', 50),
    ('grocery.food.produce.fruit.melons', 'grocery.food.produce.fruit', 'Melons', 4, 'grocery.food.produce.fruit.melons', 60),
    ('grocery.food.produce.fruit.stone_fruit', 'grocery.food.produce.fruit', 'Stone Fruit', 4, 'grocery.food.produce.fruit.stone_fruit', 70),
    ('grocery.food.produce.fruit.tropical', 'grocery.food.produce.fruit', 'Tropical Fruit', 4, 'grocery.food.produce.fruit.tropical', 80),
    ('grocery.food.produce.fruit.other', 'grocery.food.produce.fruit', 'Other Fruit', 4, 'grocery.food.produce.fruit.other', 999),
    ('grocery.food.produce.vegetables.leafy_greens', 'grocery.food.produce.vegetables', 'Leafy Greens', 4, 'grocery.food.produce.vegetables.leafy_greens', 10),
    ('grocery.food.produce.vegetables.cruciferous', 'grocery.food.produce.vegetables', 'Cruciferous Vegetables', 4, 'grocery.food.produce.vegetables.cruciferous', 20),
    ('grocery.food.produce.vegetables.root', 'grocery.food.produce.vegetables', 'Root Vegetables', 4, 'grocery.food.produce.vegetables.root', 30),
    ('grocery.food.produce.vegetables.potatoes_sweet_potatoes', 'grocery.food.produce.vegetables', 'Potatoes & Sweet Potatoes', 4, 'grocery.food.produce.vegetables.potatoes_sweet_potatoes', 40),
    ('grocery.food.produce.vegetables.tomatoes', 'grocery.food.produce.vegetables', 'Tomatoes', 4, 'grocery.food.produce.vegetables.tomatoes', 50),
    ('grocery.food.produce.vegetables.alliums', 'grocery.food.produce.vegetables', 'Onions, Garlic & Alliums', 4, 'grocery.food.produce.vegetables.alliums', 60),
    ('grocery.food.dairy_eggs_alternatives.yogurt.greek', 'grocery.food.dairy_eggs_alternatives.yogurt', 'Greek Yogurt', 4, 'grocery.food.dairy_eggs_alternatives.yogurt.greek', 10),
    ('grocery.food.dairy_eggs_alternatives.cheese.paneer', 'grocery.food.dairy_eggs_alternatives.cheese', 'Paneer', 4, 'grocery.food.dairy_eggs_alternatives.cheese.paneer', 10),
    ('grocery.food.grains_rice_pasta.rice.basmati', 'grocery.food.grains_rice_pasta.rice', 'Basmati Rice', 4, 'grocery.food.grains_rice_pasta.rice.basmati', 10),
    ('grocery.food.pulses_beans_lentils.lentils.toor_dal', 'grocery.food.pulses_beans_lentils.lentils', 'Toor Dal', 4, 'grocery.food.pulses_beans_lentils.lentils.toor_dal', 10),
    ('grocery.food.pulses_beans_lentils.chickpeas.kabuli_chana', 'grocery.food.pulses_beans_lentils.chickpeas', 'Kabuli Chana', 4, 'grocery.food.pulses_beans_lentils.chickpeas.kabuli_chana', 10)
)
insert into categories (slug, parent_id, name, depth, path_slug, sort_order)
select seed.slug, parents.id, seed.name, seed.depth, seed.path_slug, seed.sort_order
from seed
join parents on parents.slug = seed.parent_slug
on conflict (slug) do nothing;

insert into themes (slug, name, description)
values
    ('fresh', 'Fresh', 'Fresh or refrigerated item.'),
    ('frozen', 'Frozen', 'Frozen item.'),
    ('canned', 'Canned', 'Canned or jarred shelf-stable item.'),
    ('dried', 'Dried', 'Dried or dehydrated item.'),
    ('produce', 'Produce', 'Fresh produce related item.'),
    ('fruit', 'Fruit', 'Fruit item or fruit-derived product.'),
    ('vegetable', 'Vegetable', 'Vegetable item or vegetable-derived product.'),
    ('whole_food', 'Whole Food', 'Minimally processed whole food.'),
    ('organic', 'Organic', 'Organic certified or marketed item.'),
    ('high_protein', 'High Protein', 'High-protein food or supplement.'),
    ('sports_nutrition', 'Sports Nutrition', 'Sports nutrition use case.'),
    ('baby', 'Baby', 'Baby or infant use case.'),
    ('pet', 'Pet', 'Pet use case.'),
    ('household', 'Household', 'Household product or use case.'),
    ('personal_care', 'Personal Care', 'Personal care product or use case.'),
    ('medical', 'Medical', 'Medical or health-supporting product.'),
    ('prepared', 'Prepared', 'Prepared or ready-to-eat item.'),
    ('weighted', 'Weighted', 'Sold by weight.'),
    ('bulk', 'Bulk', 'Bulk-bin or large-pack item.'),
    ('imported', 'Imported', 'Imported item.')
on conflict (slug) do nothing;
