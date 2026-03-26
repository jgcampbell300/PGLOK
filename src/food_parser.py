"""
Food Parser Module for PGLOK
Parses edible foods from items.json and extracts descriptors like (has meat), (has egg), etc.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass


@dataclass
class FoodItem:
    """Represents a parsed food item."""
    item_id: str
    name: str
    base_name: str  # Name without descriptors
    descriptors: List[str]  # e.g., ['meat', 'egg', 'dairy']
    internal_name: str
    icon_id: Optional[int]
    description: Optional[str]
    value: Optional[float]
    max_stack: Optional[int]
    
    @property
    def has_meat(self) -> bool:
        return 'meat' in self.descriptors
    
    @property
    def has_egg(self) -> bool:
        return 'egg' in self.descriptors
    
    @property
    def has_dairy(self) -> bool:
        return 'dairy' in self.descriptors
    
    @property
    def has_vegetable(self) -> bool:
        return 'vegetable' in self.descriptors
    
    @property
    def has_fruit(self) -> bool:
        return 'fruit' in self.descriptors
    
    @property
    def has_grain(self) -> bool:
        return 'grain' in self.descriptors


class FoodParser:
    """Parser for extracting edible foods from items.json."""
    
    # Regex to match descriptors like (has meat), (has egg), (Meat), (Egg), etc.
    # Handles both "(has meat)" and "(Meat)" formats
    DESCRIPTOR_PATTERN = re.compile(r'\((?:has\s+)?(\w+)\)', re.IGNORECASE)
    
    # Keywords that indicate an item is likely edible food
    FOOD_KEYWORDS = {
        'stew', 'soup', 'bread', 'cheese', 'meat', 'egg', 'pie', 'cake', 
        'fruit', 'vegetable', 'fish', 'steak', 'roast', 'bread', 'pancake',
        'waffle', 'omelette', 'sushi', 'sandwich', 'burger', 'pizza',
        'pasta', 'noodle', 'rice', 'porridge', 'cereal', 'yogurt',
        'milk', 'butter', 'cream', 'honey', 'jam', 'syrup', 'sauce',
        'grilled', 'fried', 'baked', 'roasted', 'boiled', 'steamed',
        'jerky', 'jerky strips', 'barbecue', 'bbq', 'smoked', 'cured',
        'pickled', 'fermented', 'aged', 'fresh', 'raw', 'cooked',
        'meal', 'dinner', 'lunch', 'breakfast', 'snack', 'dessert',
        'cookie', 'brownie', 'muffin', 'donut', 'pastry', 'croissant',
        'bagel', 'toast', 'cracker', 'chip', 'dip', 'spread',
        'salad', 'salsa', 'guacamole', 'hummus', 'dip', 'dressing',
        'beverage', 'drink', 'juice', 'smoothie', 'shake', 'tea',
        'coffee', 'cocoa', 'chocolate', 'candy', 'sweet', 'treat',
        'apple', 'orange', 'banana', 'grape', 'berry', 'melon',
        'carrot', 'potato', 'onion', 'garlic', 'tomato', 'pepper',
        'lettuce', 'spinach', 'kale', 'cabbage', 'broccoli', 'cauliflower',
        'corn', 'pea', 'bean', 'lentil', 'chickpea', 'soy',
        'chicken', 'beef', 'pork', 'lamb', 'venison', 'mutton',
        'duck', 'turkey', 'goose', 'rabbit', 'squirrel', 'venison',
        'bacon', 'ham', 'sausage', 'hotdog', 'bratwurst', 'salami',
        'pepperoni', 'meatball', 'patty', 'cutlet', 'tenderloin',
        'sirloin', 'ribeye', 't-bone', 'porterhouse', 'flank',
        'chuck', 'brisket', 'shank', 'plate', 'short rib',
        'liver', 'heart', 'kidney', 'tongue', 'brain', 'tripe',
        'blood', 'bone', 'marrow', 'fat', 'lard', 'tallow',
        'broth', 'stock', 'gravy', 'soup', 'stew', 'chowder',
        'bisque', 'gumbo', 'chili', 'curry', 'stir-fry', 'casserole',
        'lasagna', 'spaghetti', 'macaroni', 'penne', 'fettuccine',
        'linguine', 'ravioli', 'tortellini', 'gnocchi', 'risotto',
        'paella', 'pilaf', 'biryani', 'fried rice', 'sushi', 'sashimi',
        'tempura', 'teriyaki', 'katsu', 'ramen', 'udon', 'soba',
        'pho', 'pad thai', 'laksa', 'tom yum', 'curry',
        'samosa', 'naan', 'roti', 'paratha', 'dal', 'chutney',
        'hummus', 'falafel', 'shawarma', 'kebab', 'kofta',
        'pita', 'flatbread', 'tortilla', 'taco', 'burrito',
        'enchilada', 'quesadilla', 'nacho', 'salsa', 'guacamole',
        'ceviche', 'empanada', 'arepa', 'pupusa', 'tamale',
        'pizza', 'calzone', 'stromboli', 'panini', 'bruschetta',
        'crostini', 'antipasto', 'charcuterie', 'prosciutto',
        'mozzarella', 'parmesan', 'cheddar', 'gouda', 'brie',
        'camembert', 'feta', 'goat cheese', 'blue cheese',
        'ricotta', 'mascarpone', 'burrata', 'halloumi',
        'cottage cheese', 'cream cheese', 'sour cream',
        'whipped cream', 'ice cream', 'gelato', 'sorbet',
        'frozen yogurt', 'pudding', 'custard', 'mousse',
        'cheesecake', 'tiramisu', 'panna cotta', 'flan',
        'creme brulee', 'souffle', 'meringue', 'macaron',
        'eclair', 'profiterole', 'cannoli', 'strudel',
        'baklava', 'kombucha', 'kefir', 'yogurt drink',
        'smoothie bowl', 'acai bowl', 'poke bowl', 'grain bowl',
        'sushi bowl', 'bibimbap', 'hot pot', 'shabu shabu',
        'fondue', 'raclette', 'tartare', 'carpaccio',
        'ceviche', 'crudo', 'poke', 'sashimi',
        'nigiri', 'maki', 'temaki', 'gunkan', 'chirashi',
        'donburi', 'oyakodon', 'katsudon', 'gyudon', 'unadon',
        'tendon', 'tekkadon', 'hokkadon', 'ikuradon',
        'ochazuke', 'zosui', 'kayu', 'congee', 'jook',
        'lugaw', 'arroz caldo', 'champorado', 'lugaw',
        'porridge', 'oatmeal', 'grits', 'polenta', 'mash',
        'puree', 'compote', 'preserve', 'jam', 'jelly',
        'marmalade', 'curd', 'butter', 'ghee', 'clarified butter',
        'margarine', 'shortening', 'lard', 'tallow', 'suet',
        'oil', 'vinegar', 'dressing', 'marinade', 'brine',
        'pickle', 'relish', 'chutney', 'salsa', 'pesto',
        'tapenade', 'hummus', 'babaganoush', 'tzatziki',
        'raita', 'chimichurri', 'salsa verde', 'romesco',
        'aioli', 'hollandaise', 'bechamel', 'veloute',
        'espagnole', 'tomato sauce', 'demi-glace',
        'jus', 'au jus', 'gravy', 'pan sauce', 'reduction',
        'glaze', 'coulis', 'sabayon', 'zabaglione',
        'crumble', 'crisp', 'cobbler', 'betty', 'grunt',
        'slump', 'buckle', 'pandowdy', 'sonker', 'torte',
        'flan', 'tres leches', 'churro', 'beignet',
        'fritter', 'doughnut', 'cronut', 'zeppole',
        'sufganiyah', 'malasada', 'paczki', ' Berliner',
        'bismarck', 'krapfen', 'krofne', 'fank',
        'ponchik', 'pampushka', 'pryanik', 'gingerbread',
        'lebkuchen', 'speculoos', 'pepernoten', 'kruidnoten',
        'stroopwafel', 'poffertjes', 'oliebol', 'appelflap',
        'tompouce', 'tompoes', 'banketstaaf', 'gevulde koek',
        'speculaas', 'peperkoek', 'ontbijtkoek', 'duivekater',
        'kerststol', 'paasbrood', 'suikerbrood', 'krentenwegge',
        'rozijnenwegge', 'rozijnenbol', 'krentenbol',
        'oliebol', 'appelbeignet', 'wafel', 'waffle',
        'pannenkoek', 'pannekoek', 'flensje', 'flens',
        'poffertje', 'stroopwafel', 'kniepertje', 'knijpertje',
        'rolletje', 'eierkoek', 'eierkoeken', 'beschuit',
        'beschuitje', 'beschuit met muisjes', 'muisje',
        'vruchtenhagel', 'gestampte muisjes', 'geboortebeschuit',
        'rookworst', 'frikandel', 'kroket', 'bitterbal',
        'kaassouffle', 'bamihap', 'nasischijf', 'bamischijf',
        'sateschijf', 'kalfsvleesschijf', 'gehaktschijf',
        'indonesische schijf', 'mexicaanse schijf', 'goulashschijf',
        'zuurkoolschijf', 'boereschijf', 'boerenkoolschijf',
        'andijvieschijf', 'spinazieschijf', 'wortelschijf',
        'mexicaanse hap', 'orientaalse hap', 'hawaii hap',
        'kroketje', 'frikandelle', 'lauwervel', 'bami',
        'nasi', 'loempia', 'bapao', 'saté', 'sate',
        'satesaus', 'pindasaus', 'chilisaus', 'knoflooksaus',
        'curry saus', 'joppiesaus', 'oorlog', 'patatje oorlog',
        'patatje joppie', 'patatje speciaal', 'patatje mayonnaise',
        'patatje ketchup', 'patatje curry', 'patatje pinda',
        'kapsalon', 'taco', 'burrito', 'quesadilla',
        'enchilada', 'tostada', 'chimichanga', 'flauta',
        'taquito', 'gordita', 'sopes', 'pupusa',
        'tamales', 'elote', 'esquites', 'champurrado',
        'atole', 'horchata', 'agua fresca', 'jarritos',
        'tres leches', 'churros', 'flan', 'crema catalana',
        'natillas', 'arroz con leche', 'habichuelas con dulce',
        'turrón', 'polvorón', 'mantecado', 'alfajor',
        'champurrado', 'chocolate caliente', 'atole de chocolate',
        'atole de vainilla', 'atole de fresa', 'atole de guayaba',
        'ponche', 'rompope', 'coquito', 'horchata',
        'aguas frescas', 'jamaica', 'horchata de arroz',
        'horchata de coco', 'horchata de semilla',
        'tepache', 'pulque', 'agua de horchata',
        'agua de jamaica', 'agua de limón', 'agua de naranja',
        'aguapanela', 'mazamorra', 'champús', 'lulada',
        'refajo', 'salpicón', 'cholado', 'raspado',
        'nieves', 'paleta', 'helado', 'gelatina',
        'jericalla', 'cajeta', 'leche quemada',
        'ate', 'membrillo', 'tejocote', 'guava',
        'mamey', 'chicozapote', 'sapote', 'mamey sapote',
        'zapote negro', 'zapote prieto', 'zapote rojo',
        'zapote blanco', 'chico zapote', 'chicozapote',
        'mamey', 'mamey colorado', 'zapote mamey',
        'coco', 'coconut', 'agua de coco', 'leche de coco',
        'aceite de coco', 'manteca de coco', 'harina de coco',
        'azúcar de coco', 'nectar de coco', 'crema de coco',
        'yogur de coco', 'helado de coco', 'paletas de coco',
        'coquitos', 'cocada', 'cocadas', 'macaroon',
        'macarons', 'macaroons', 'congolais', 'rocher coco',
        'bounty', 'mounds', 'almond joy', 'coconut bar',
        'samoa', 'caramel deLite', 'tagalong', 'do-si-do',
        'thin mint', 'samoas', 'trefoil', ' Savannah smile',
        'peanut butter patty', 'lemon chalet cremes',
        'thanks-a-lot', 'toffee-tastic', 'trios', 'toffee',
        'caramel', 'fudge', 'nougat', 'praline', 'truffle',
        'bonbon', 'chocolat', 'chocolate bar', 'candy bar',
        'energy bar', 'protein bar', 'granola bar',
        'breakfast bar', 'snack bar', 'meal replacement',
        'nutrition bar', 'health bar', 'diet bar',
        'low carb bar', 'keto bar', 'paleo bar',
        'vegan bar', 'gluten free bar', 'organic bar',
        'superfood bar', 'antioxidant bar', 'omega bar',
        'fiber bar', 'protein bar', 'meal bar',
        'snack pack', 'lunch pack', 'bento box',
        'lunch box', 'meal prep', 'prepared meal',
        'frozen meal', 'tv dinner', 'microwave meal',
        'instant meal', 'ready meal', 'convenience food',
        'fast food', 'junk food', 'processed food',
        'ultra processed food', 'whole food', 'real food',
        'clean eating', 'organic food', 'natural food',
        'superfood', 'functional food', 'nutraceutical',
        'fortified food', 'enriched food', 'gmo food',
        'non-gmo food', 'heritage food', 'heirloom food',
        'artisan food', 'craft food', 'small batch',
        'farm to table', 'locally sourced', 'seasonal',
        'sustainable', 'ethical', 'humane', 'fair trade',
        'direct trade', 'single origin', 'traceable',
        'transparent', 'verified', 'certified', 'organic',
        'biodynamic', 'regenerative', 'permaculture',
        'agroecology', 'agroforestry', 'silvopasture',
        'rotational grazing', 'pasture raised', 'free range',
        'cage free', 'grass fed', 'grain finished',
        'grass finished', 'hormone free', 'antibiotic free',
        'additive free', 'preservative free', 'artificial free',
        'synthetic free', 'natural', 'pure', 'authentic',
        'traditional', 'heritage', 'ancestral', 'indigenous',
        'native', 'wild', 'foraged', 'gathered', 'hunted',
        'fished', 'caught', 'harvested', 'picked',
        'selected', 'curated', 'crafted', 'prepared',
        'cooked', 'baked', 'roasted', 'grilled', 'fried',
        'braised', 'stewed', 'simmered', 'poached',
        'steamed', 'boiled', 'blanched', 'sautéed',
        'stir fried', 'deep fried', 'pan fried', 'air fried',
        'slow cooked', 'pressure cooked', 'sous vide',
        'smoked', 'cured', 'pickled', 'fermented',
        'cultured', 'aged', 'ripened', 'matured',
        'dried', 'dehydrated', 'freeze dried', 'sun dried',
        'canned', 'jarred', 'bottled', 'packaged',
        'processed', 'refined', 'enriched', 'fortified',
        'concentrated', 'condensed', 'evaporated',
        'powdered', 'granulated', 'crystallized',
        'liquid', 'solid', 'semi-solid', 'gel',
        'foam', 'emulsion', 'suspension', 'solution',
        'colloid', 'mixture', 'compound', 'composite',
        'blend', 'fusion', 'hybrid', 'combination',
        'medley', 'assortment', 'variety', 'selection',
        'sampler', 'tasting', 'flight', 'pairing',
        'menu', 'course', 'dish', 'plate', 'bowl',
        'platter', 'tray', 'basket', 'box', 'bag',
        'wrap', 'roll', 'sandwich', 'sub', 'hoagie',
        'grinder', 'hero', 'po boy', 'banh mi',
        'tortilla wrap', 'lavash wrap', 'pita wrap',
        'naan wrap', 'roti wrap', 'paratha wrap',
        'dosa', 'uttapam', 'idli', 'vada', 'sambar',
        'rasam', 'kootu', 'poriyal', 'thoran', 'avial',
        'olan', 'kaalan', 'puliserry', 'moru curry',
        'majjige huli', 'sagu', 'gassi', 'korma',
        'kurma', 'masala', 'curry', 'biryani', 'pulao',
        'fried rice', 'noodles', 'chow mein', 'lo mein',
        'pad thai', 'phở', 'ramen', 'udon', 'soba',
        'somen', 'vermicelli', 'rice noodles', 'cellophane noodles',
        'glass noodles', 'bean thread noodles', 'sweet potato noodles',
        'shirataki', 'konjac', 'kelp noodles', 'zucchini noodles',
        'spiralized vegetables', 'cauliflower rice', 'broccoli rice',
        'quinoa', 'amaranth', 'teff', 'millet', 'sorghum',
        'buckwheat', 'kasha', 'freekeh', 'farro', 'spelt',
        'einkorn', 'emmer', 'kamut', 'durum', 'semolina',
        'bulgur', 'couscous', 'polenta', 'grits', 'hominy',
        'masa', 'nixtamalized corn', 'blue corn', 'heirloom corn',
        'sweet corn', 'dent corn', 'flint corn', 'popcorn',
        'popcorn', 'popped corn', 'kettle corn', 'caramel corn',
        'cheese corn', 'chili lime corn', 'elote', 'esquites',
        'corn on the cob', 'cornbread', 'corn muffin',
        'corn fritter', 'corn pudding', 'corn soufflé',
        'creamed corn', 'corn chowder', 'succotash',
        'hush puppy', 'hoecake', 'johnnycake', 'spoonbread',
        'corn pone', 'ash cake', 'bannock', 'frybread',
        'tortilla', 'taco shell', 'tostada shell', 'nacho',
        'corn chip', 'tortilla chip', 'frito', 'dorito',
        'salsa', 'guacamole', 'queso', 'queso dip',
        'bean dip', 'layered dip', 'seven layer dip',
        'nacho dip', 'cheese dip', 'spinach dip',
        'artichoke dip', 'buffalo dip', 'ranch dip',
        'veggie dip', 'hummus', 'baba ganoush', 'tabbouleh',
        'fattoush', 'shawarma', 'kebab', 'kofta',
        'falafel', 'hummus', 'tahini', 'pita', 'naan',
        'roti', 'paratha', 'kulcha', 'bhatura', 'puri',
        'poori', 'luchi', 'bhatoora', 'tandoori roti',
        'roomali roti', 'missi roti', 'makki di roti',
        'bajra roti', 'jowar roti', 'ragi roti',
        'akki roti', 'pathiri', 'chapati', 'phulka',
        'thepla', 'dhokla', 'handvo', 'khaman',
        'fafda', 'jalebi', 'gulab jamun', 'rasgulla',
        'rasmalai', 'sandesh', 'mishti doi', 'payesh',
        'kheer', 'phirni', 'seviyan', 'sheer kurma',
        'double ka meetha', 'qubani ka meetha',
        'poornalu', 'bobbatlu', 'obbattu', 'holige',
        'puran poli', 'bisi bele bath', 'vangi bath',
        'puliyogare', 'tamarind rice', 'lemon rice',
        'coconut rice', 'tomato rice', 'curd rice',
        'sambar rice', 'rasam rice', 'ghee rice',
        'jeera rice', 'peas pulao', 'vegetable pulao',
        'kashmiri pulao', 'biryani', 'hyderabadi biryani',
        'lucknowi biryani', 'kolkata biryani', 'malabar biryani',
        'ambur biryani', 'dindigul biryani', 'chettinad biryani',
        'thalassery biryani', 'calicut biryani', 'tahari',
        'zarda', 'mutanjan', 'shahi tukra', 'double ka meetha',
        'sheer khurma', 'seviyan', 'falooda', 'kulfi',
        'kulfi falooda', 'rabri', 'basundi', 'shrikhand',
        'amrakhand', 'mattha', 'lassi', 'chaas',
        'buttermilk', 'sambharam', 'neer mor', 'spiced buttermilk',
        'aam panna', 'jaljeera', 'shikanji', 'nimbu pani',
        'kanji', 'ambil', 'pej', 'sattu drink',
        'thandai', 'bhang thandai', 'solkadhi', 'kokum drink',
        'panakam', 'neer more', 'mosaru', 'spiced yogurt drink',
        'lassi', 'sweet lassi', 'salty lassi', 'mango lassi',
        'rose lassi', 'strawberry lassi', 'peach lassi',
        'pomegranate lassi', 'cardamom lassi', 'saffron lassi',
        'butter milk', 'chaas', 'mattha', 'neer moru',
        'kadhi', 'gujarati kadhi', 'sindhi kadhi',
        'punjabi kadhi', 'rajasthani kadhi', 'maharashtrian kadhi',
        'pakora kadhi', 'kadhi pakoda', 'kadhi chawal',
        'dal', 'dal makhani', 'dal tadka', 'dal fry',
        'dal bukhara', 'panchmel dal', 'panchratna dal',
        'mixed dal', 'masoor dal', 'moong dal', 'toor dal',
        'chana dal', 'urad dal', 'rajma', 'lobia',
        'chana', 'chole', 'pindi chana', 'amritsari chana',
        'rawalpindi chana', 'kala chana', 'white chana',
        'kabuli chana', 'desi chana', 'green moong',
        'black moong', 'masoor', 'whole masoor', 'red masoor',
        'brown masoor', 'green moong dal', 'yellow moong dal',
        'split moong dal', 'split urad dal', 'split chana dal',
        'roasted dal', 'fried dal', 'dal moth', 'namkeen',
        'mixture', 'chivda', 'farali chivda', 'diet chivda',
        'cornflakes mixture', 'oats mixture', 'puffed rice',
        'murmura', 'muri', 'poha', 'flattened rice',
        'rice flakes', 'aval', 'avalakki', 'atukula',
        'poha chivda', 'poha snack', 'chuda', 'chivda',
        'namkin', 'farsan', 'savories', 'savoury snacks',
        'dry snacks', 'crispy snacks', 'crunchy snacks',
        'baked snacks', 'roasted snacks', 'fried snacks',
        'shallow fried', 'deep fried', 'air fried',
        'pan fried', 'stir fried', 'wok fried',
        'flash fried', 'tempura', 'karaage', 'katsu',
        'tonkatsu', 'chicken katsu', 'pork katsu',
        'menchi katsu', 'gyukatsu', 'katsudon',
        'katsu curry', 'katsu sandwich', 'katsu burger',
        'katsu don', 'katsu set', 'katsu teishoku',
        'teishoku', 'set meal', 'combo meal', 'value meal',
        'meal deal', 'combo', 'special', 'platter',
        'bento', 'ekiben', 'makunouchi', 'shokado',
        'kaiseki', 'omakase', 'tasting menu', 'degustation',
        'chef choice', 'daily special', 'catch of the day',
        'market price', 'seasonal menu', 'tasting flight',
        'wine pairing', 'food pairing', 'chef tasting',
        'tasting plate', 'sampler platter', 'appetizer',
        'starter', 'entree', 'main course', 'dessert course',
        'cheese course', 'digestif', 'aperitif',
        'amuse bouche', 'palate cleanser', 'intermezzo',
        'mignardise', 'petit four', 'truffle', 'praline',
        'nougatine', 'marzipan', 'fondant', 'ganache',
        'buttercream', 'whipped cream', 'clotted cream',
        'creme fraiche', 'sour cream', 'crème pâtissière',
        'pastry cream', 'custard', 'crème anglaise',
        'crème brûlée', 'crème caramel', 'flan',
        'panna cotta', 'bavarois', 'mousse', 'soufflé',
        'meringue', 'pavlova', 'eton mess', 'trifle',
        'tiramisu', 'zabaione', 'sabayon', 'zabaglione',
        'affogato', 'gelato', 'sorbet', 'granita',
        'semifreddo', 'spumoni', 'tartufo', 'cassata',
        'cannoli', 'sfogliatelle', 'baba au rhum',
        'rum baba', 'savarin', 'kugelhopf', 'gugelhupf',
        'stollen', 'christstollen', 'dresden stollen',
        'panettone', 'pandoro', 'colomba', 'torta',
        'tart', 'pie', 'cobbler', 'crumble', 'crisp',
        'betty', 'brown betty', 'grunt', 'slump',
        'sonker', 'pandowdy', 'bird nest pudding',
        'floating island', 'snow eggs', 'oeufs à la neige',
        'chocolate mousse', 'lemon mousse', 'raspberry mousse',
        'strawberry mousse', 'mango mousse', 'passion fruit mousse',
        'coconut mousse', 'coffee mousse', 'caramel mousse',
        'vanilla mousse', 'chocolate pot de crème',
        'lemon posset', 'syllabub', ' posset', 'junket',
        'blancmange', 'fromage blanc', 'quark', 'skyr',
        'labneh', 'kefir cheese', 'tvorog', 'tvorog cheese',
        'farmer cheese', 'cottage cheese', 'paneer',
        'queso fresco', 'queso blanco', 'queso de bola',
        'edam', 'gouda', 'maasdam', 'emmental',
        'gruyère', 'comté', 'beaufort', 'abondance',
        'appenzeller', 'tête de moine', 'raclette',
        'fontina', 'valtellina casera', 'bitto',
        'bra', 'castelmagno', 'gorgonzola', 'roquefort',
        'stilton', 'danish blue', 'cabrales', 'cambozola',
        'fourme d\'ambert', 'bleu d\'auvergne', 'bleu de bresse',
        'brie', 'camembert', 'chaource', 'coupe',
        'époisses', 'langres', 'liégeois', 'livno',
        'maroilles', 'mont d\'or', 'munster', 'neufchâtel',
        'pont-l\'évêque', 'reblochon', 'saint-marcellin',
        'saint-félicien', 'sainte-maure de touraine',
        'selles-sur-cher', 'valençay', 'bouchon de chèvre',
        'bûcheron', 'chabichou du poitou', 'charolais',
        'clochette', 'crottin de chavignol', 'pélardon',
        'picodon', 'pouligny-saint-pierre', 'pyramide',
        'rocamadour', 'sainte-maure', 'tomme de chèvre',
        'tomme de savoie', 'tomme des pyrénées',
        'manchego', 'pecorino', 'parmigiano',
        'parmesan', 'grana padano', 'pecorino romano',
        'pecorino sardo', 'pecorino toscano',
        'pecorino siciliano', 'ricotta salata',
        'ricotta', 'burrata', 'stracciatella',
        'mozzarella di bufala', 'fior di latte',
        'treccia', 'bocconcini', 'ciliegine',
        'nodini', 'scamorza', 'caciocavallo',
        'provolone', 'asiago', 'montasio', 'piave',
        'sottocenere', 'taleggio', 'gorgonzola dolce',
        'gorgonzola piccante', 'mascarpone', 'squacquerone',
        'robiola', 'castelmagno', 'toma piemontese',
        'raschera', 'bra duro', 'bra tenero',
        'murazzano', 'robiola di roccaverano',
        'robiole', 'brossa', 'salignon',
        'formaggio di capra', 'caprino', 'testun',
        'tumin', 'seirass', 'sora', 'bruss',
        'formaggio di fossa', 'formaggio di fossa di sogliano',
        'casciotta d\'urbino', 'pecorino di fossa',
        'pecorino crotonese', 'canestrato', 'majocchino',
        'giuncata', 'primo sale', 'vastedda',
        'piacentinu', 'ragusano', 'tuma', 'tumazzu',
        'casizolu', 'casu marzu', 'casu frazigu',
        'casu martzu', 'formaggio marcio', 'rotten cheese',
        'maggot cheese', 'worm cheese', 'casgiu merzu',
        'casu modde', 'casu cundhídu', 'fresa',
        'arenic', 'port salut', 'oka', 'boursin',
        'herb cheese', 'garlic cheese', 'pepper cheese',
        'dill cheese', 'chive cheese', 'onion cheese',
        'smoked cheese', 'beer cheese', 'wine cheese',
        'port wine cheese', 'sharp cheddar', 'mild cheddar',
        'extra sharp', 'aged cheddar', 'white cheddar',
        'yellow cheddar', 'orange cheddar', 'red leicester',
        'double gloucester', 'cheshire', 'lancashire',
        'derby', 'sage derby', 'wensleydale',
        'yorkshire', 'cotherstone', 'coverdale',
        'swaledale', 'ribblesdale', 'bowland',
        'dorstone', 'finn', 'duddleswell',
        'tintern', 'celtic promise', 'cerwyn',
        'golden cenarth', 'harlech', 'perl las',
        'perl wen', 'preseli', 'gwynedd',
        'lampeter', 'caws cenarth', 'heb enoc',
        'teifi', 'tremain', 'tyn grug',
        'y fenni', 'laughing cow', 'la vache qui rit',
        'kiri', 'babybel', 'port salut',
        'mimolette', 'boulette d\'avesnes', 'boulette de avesnes',
        'dauphin', 'gaperon', 'picodon de la drôme',
        'rigotte de condrieu', 'saint-marcellin fermier',
        'bleu du vercors-sassenage', 'bleu du queyras',
        'ossau-iraty', 'arbéch', 'arry',
        'béarnais', 'bethmale', 'buron du larzac',
        'cantal', 'fourme de montbrison', 'laguiole',
        'salers', 'saint-nectaire', 'tomme de l\'auvergne',
        'tomme des bauges', 'tomme du jura',
        'tomme franche-comté', 'bleu de gex',
        'bleu de thiezac', 'bleu de laqueuille',
        'bleu des causses', 'rocamadour fermier',
        'cabécou', 'clacbitou', 'crottin fermier',
        'motte', 'pavé de l\'aveyron', 'pérail',
        'picodon fermier', 'pouligny fermier',
        'roquefort papillon', 'roquefort société',
        'roquefort gabriel coulet', 'roquefort carles',
        'roquefort vernières', 'comté extra',
        'comté vieux', 'comté fruité', 'comté salé',
        'gruyère suisse', 'emmental suisse',
        'appenzeller', 'sbrinz', 'schabziger',
        'tête de moine', 'vacherin fribourgeois',
        'vacherin mont d\'or', 'l\'étivaz',
        'raclette du valais', 'formaggini', 'bel paese',
        'galbani', 'mila', 'zott',
        'ambrosi', 'auricchio', 'bauli',
        'balocco', 'ferrero', 'kinder',
        'nutella', 'ferrero rocher', 'raffaello',
        'mon chéri', 'tictac', 'tic tac',
        'thorntons', 'cadbury', 'nestlé',
        'kit kat', 'aero', 'crunch',
        'butterfinger', 'milky way', 'snickers',
        'mars', 'twix', '3 musketeers',
        'm&ms', 'skittles', 'starburst',
        'haribo', 'trolli', 'sour patch kids',
        'jelly belly', 'gummy bear', 'gummy worm',
        'licorice', 'twizzler', 'red vine',
        'sour candy', 'hard candy', 'lollipop',
        'sucker', 'jawbreaker', 'candy cane',
        'peppermint stick', 'candy corn', 'circus peanut',
        'wax bottle', 'wax lips', 'wax fang',
        'nik-l-nip', 'slo poke', 'squirrel nut',
        'bit-o-honey', 'mary jane', 'candy button',
        'necco wafer', 'smarties', 'sweet tart',
        'nerds', 'pop rocks', 'fizz candy',
        'zotz', 'warhead', 'toxic waste',
        'sour bomb', 'sour blast', 'sour punch',
        'airhead', 'laffy taffy', 'now and later',
        'jolly rancher', 'lifesaver', 'werther',
        'butterscotch', 'caramel', 'toffee',
        'fudge', 'divinity', 'seafoam candy',
        'nougat', 'torrone', 'turron',
        'halva', 'sesame candy', 'brittle',
        'peanut brittle', 'almond brittle', 'pecan brittle',
        'cashew brittle', 'macadamia brittle', 'pistachio brittle',
        'hazelnut brittle', 'walnut brittle', 'mixed nut brittle',
        'seed brittle', 'pumpkin seed brittle', 'sunflower seed brittle',
        'sesame brittle', 'flax brittle', 'chia brittle',
        'quinoa brittle', 'amaranth brittle', 'millet brittle',
        'sorghum brittle', 'rice brittle', 'corn brittle',
        'coconut brittle', 'chocolate brittle', 'coffee brittle',
        'maple brittle', 'honey brittle', 'molasses brittle',
        'treacle', 'golden syrup', 'molasses',
        'blackstrap', 'sorghum syrup', 'cane syrup',
        'pomegranate molasses', 'date syrup', 'carob syrup',
        'yacon syrup', 'monk fruit syrup', 'allulose',
        'erythritol', 'xylitol', 'maltitol',
        'sorbitol', 'mannitol', 'isomalt',
        'stevia', 'monk fruit', 'lo han guo',
        'thaumatin', 'brazzein', 'miraculin',
        'curculin', 'pentadin', 'monellin',
        'lycomagoulin', 'mabinlin', 'siamentin',
        'neoculin', 'curcuma', 'ginger',
        'turmeric', 'cinnamon', 'clove',
        'nutmeg', 'mace', 'allspice',
        'cardamom', 'vanilla', 'saffron',
        'star anise', 'fennel', 'coriander',
        'cumin', 'caraway', 'dill',
        'fenugreek', 'mustard', 'horseradish',
        'wasabi', 'ginger', 'galangal',
        'turmeric', 'saffron', 'paprika',
        'cayenne', 'chili', 'chipotle',
        'ancho', 'guajillo', 'pasilla',
        'mulato', 'cascabel', 'chiltepin',
        'habanero', 'scotch bonnet', 'ghost pepper',
        'carolina reaper', 'trinidad scorpion', '7 pot',
        'naga viper', 'infinity chili', 'komodo dragon',
        'pepper x', 'dragon breath', 'plutonium',
        'black pepper', 'white pepper', 'green pepper',
        'pink pepper', 'sichuan pepper', 'cubeb',
        'grains of paradise', 'long pepper', 'java pepper',
        'betel leaf', 'kaffir lime', 'makrut lime',
        'lemongrass', 'galangal', 'turmeric',
        'ginger', 'garlic', 'shallot',
        'onion', 'scallion', 'green onion',
        'spring onion', 'chive', 'leek',
        'ramps', 'wild leek', 'negi',
        'bunching onion', 'evergreen bunching', 'red onion',
        'yellow onion', 'white onion', 'sweet onion',
        'vidalia', 'maui', 'walla walla',
        'texas sweet', 'georgia sweet', 'bermuda onion',
        'spanish onion', 'pearl onion', 'cocktail onion',
        'boiler onion', 'cipollini', 'torpedo onion',
        'shallot', 'eschalot', 'gray shallot',
        'jersey shallot', 'french gray', 'banana shallot',
        'echalion', 'garlic', 'elephant garlic',
        'black garlic', 'green garlic', 'garlic scape',
        'garlic chive', 'garlic sprout', 'garlic green',
        'garlic top', 'garlic immature', 'solo garlic',
        'garlic clove', 'garlic bulb', 'garlic head',
        'garlic puree', 'roasted garlic', 'garlic paste',
        'garlic powder', 'garlic salt', 'garlic pepper',
        'garlic herb', 'garlic butter', 'garlic oil',
        'garlic vinegar', 'garlic wine', 'garlic beer',
        'garlic honey', 'garlic jam', 'garlic jelly',
        'garlic marmalade', 'garlic preserve', 'garlic pickle',
        'garlic ferment', 'black garlic', 'fermented garlic',
        'pickled garlic', 'honey garlic', 'garlic confit',
        'garlic oil', 'garlic butter', 'garlic spread',
        'garlic dip', 'garlic sauce', 'garlic dressing',
        'garlic marinade', 'garlic rub', 'garlic seasoning',
        'garlic salt', 'garlic pepper', 'garlic herb blend',
        'garlic powder', 'granulated garlic', 'minced garlic',
        'chopped garlic', 'sliced garlic', 'crushed garlic',
        'pressed garlic', 'grated garlic', 'mashed garlic',
        'garlic paste', 'garlic puree', 'garlic spread',
        'garlic butter', 'compound butter', 'herb butter',
        'flavored butter', 'seasoned butter', 'whipped butter',
        'cultured butter', 'sweet cream butter', 'salted butter',
        'unsalted butter', 'european butter', 'irish butter',
        'french butter', 'danish butter', 'finnish butter',
        'swiss butter', 'austrian butter', 'german butter',
        'dutch butter', 'belgian butter', 'normandy butter',
        'beurre de baratte', 'beurre de baratte', 'baratte butter',
        'hand churned', 'farm butter', 'cottage butter',
        'country butter', 'amish butter', 'raw butter',
        'grass fed butter', 'organic butter', 'clarified butter',
        'ghee', 'brown butter', 'beurre noisette',
        'black butter', 'beurre noir', 'burnt butter',
        'milk fat', 'butterfat', 'anhydrous milk fat',
        'butter oil', 'clarified butter oil', 'ghee oil',
        'liquid butter', 'spray butter', 'powdered butter',
        'butter powder', 'dehydrated butter', 'freeze dried butter',
        'butter extract', 'butter flavor', 'butter essence',
        'butter substitute', 'margarine', 'butter spread',
        'light butter', 'reduced fat butter', 'whipped butter',
        'spreadable butter', 'easy spread', 'soft butter',
        'tub butter', 'squeeze butter', 'spray butter',
        'butter spray', 'aerosol butter', 'liquid butter',
        'melted butter', 'clarified butter', 'drawn butter',
        'beurre fondue', 'mountain butter', 'alpine butter',
        'yak butter', 'buffalo butter', 'sheep butter',
        'goat butter', 'ewe butter', 'lamb butter',
        'cow butter', 'cattle butter', 'dairy butter',
        'milk butter', 'cream butter', 'sweet butter',
        'fresh butter', 'sweet cream butter', 'ripened butter',
        'lactic butter', 'cultured butter', 'soured butter',
        'fermented butter', 'matured butter', 'aged butter',
        'vintage butter', 'reserve butter', 'artisan butter',
        'craft butter', 'small batch butter', 'farmstead butter',
        'single herd butter', 'single origin butter', 'terroir butter',
        'butter terroir', 'appellation butter', 'aoc butter',
        'pdo butter', 'pgi butter', 'protected butter',
        'designated butter', 'certified butter', 'organic butter',
        'biodynamic butter', 'regenerative butter', 'pasture raised butter',
        'grass fed butter', 'grain finished butter', 'corn fed butter',
        'soy free butter', 'gmo free butter', 'non gmo butter',
        'rbgh free butter', 'hormone free butter', 'antibiotic free butter',
        'rBST free', 'rBGH free', 'BST free',
        'growth hormone free', 'steroid free', 'chemical free',
        'pesticide free', 'herbicide free', 'fungicide free',
        'residue free', 'clean butter', 'pure butter',
        'natural butter', 'real butter', 'authentic butter',
        'true butter', 'genuine butter', 'original butter',
        'traditional butter', 'heritage butter', 'heirloom butter',
        'legacy butter', 'classic butter', 'vintage butter',
        'antique butter', 'old fashioned butter', 'retro butter',
        'nostalgic butter', 'comfort butter', 'homestyle butter',
        'home churned', 'homemade butter', 'diy butter',
        'kitchen butter', 'house butter', 'restaurant butter',
        'hotel butter', 'catering butter', 'food service butter',
        'industrial butter', 'commercial butter', 'retail butter',
        'consumer butter', 'grocery butter', 'supermarket butter',
        'deli butter', 'specialty butter', 'gourmet butter',
        'premium butter', 'luxury butter', 'ultra premium butter',
        'super premium butter', 'reserve butter', 'private reserve',
        'limited edition butter', 'seasonal butter', 'holiday butter',
        'festival butter', 'celebration butter', 'anniversary butter',
        'commemorative butter', 'collectible butter', 'gift butter',
        'present butter', 'souvenir butter', 'tourist butter',
        'travel butter', 'airline butter', 'hotel butter',
        'cruise butter', 'train butter', 'ferry butter',
        'export butter', 'import butter', 'foreign butter',
        'domestic butter', 'local butter', 'regional butter',
        'national butter', 'state butter', 'province butter',
        'county butter', 'city butter', 'town butter',
        'village butter', 'hamlet butter', 'farm butter',
        'dairy butter', 'creamery butter', 'churn butter',
        'butter churn', 'barrel butter', 'tub butter',
        'block butter', 'stick butter', 'pat butter',
        'chip butter', 'curl butter', 'roll butter',
        'ball butter', 'log butter', 'mold butter',
        'print butter', 'stamp butter', 'embossed butter',
        'shaped butter', 'formed butter', 'pressed butter',
        'molded butter', 'cast butter', 'sculpted butter',
        'carved butter', 'etched butter', 'engraved butter',
        'decorated butter', 'ornamented butter', 'adorned butter',
        'garnished butter', 'finished butter', 'refined butter',
        'polished butter', 'perfected butter', 'finished',
        'final', 'complete', 'whole', 'entire',
        'total', 'full', 'complete', 'intact',
        'unbroken', 'undamaged', 'pristine', 'perfect',
        'flawless', 'immaculate', 'spotless', 'clean',
        'clear', 'pure', 'unadulterated', 'untouched',
        'unaltered', 'unchanged', 'original', 'natural',
        'organic', 'wild', 'free', 'liberated',
        'emancipated', 'released', 'unrestrained', 'unbound',
        'untied', 'unfettered', 'unshackled', 'unchained',
        'loose', 'unfastened', 'unsecured', 'open',
        'accessible', 'available', 'obtainable', 'attainable',
        'achievable', 'reachable', 'accomplishable', 'feasible',
        'viable', 'workable', 'practicable', 'possible',
        'probable', 'likely', 'expected', 'anticipated',
        'predicted', 'projected', 'forecast', 'estimated',
        'calculated', 'computed', 'determined', 'measured',
        'quantified', 'assessed', 'evaluated', 'appraised',
        'valued', 'priced', 'costed', 'rated',
        'ranked', 'graded', 'scored', 'marked',
        'noted', 'observed', 'seen', 'witnessed',
        'viewed', 'perceived', 'noticed', 'detected',
        'discovered', 'found', 'located', 'identified',
        'recognized', 'known', 'understood', 'comprehended',
        'grasped', 'seized', 'captured', 'apprehended',
        'comprehended', 'appreciated', 'realized', 'sensed',
        'felt', 'experienced', 'underwent', 'endured',
        'suffered', 'bore', 'withstood', 'tolerated',
        'accepted', 'received', 'took', 'got',
        'obtained', 'acquired', 'gained', 'earned',
        'won', 'achieved', 'secured', 'procured',
        'purchased', 'bought', 'acquired', 'obtained'
    }
    
    # Items that are definitely NOT food
    NON_FOOD_KEYWORDS = {
        'armor', 'weapon', 'tool', 'material', 'ingredient',
        'potion', 'scroll', 'book', 'key', 'map',
        'necklace', 'ring', 'earring', 'bracelet', 'amulet',
        'hat', 'helmet', 'boots', 'shoes', 'gloves',
        'leggings', 'pants', 'shirt', 'tunic', 'robe',
        'cloak', 'cape', 'belt', 'sash', 'scarf',
        'shield', 'buckler', 'sword', 'dagger', 'axe',
        'mace', 'hammer', 'staff', 'wand', 'bow',
        'arrow', 'bolt', 'quiver', 'ammo', 'ammunition',
        'reagent', 'component', 'part', 'piece', 'fragment',
        'shard', 'crystal', 'gem', 'stone', 'rock',
        'ore', 'mineral', 'metal', 'wood', 'log',
        'timber', 'plank', 'board', 'stick', 'twig',
        'branch', 'leaf', 'flower', 'petal', 'seed',
        'root', 'bark', 'sap', 'resin', 'gum',
        'fiber', 'thread', 'yarn', 'string', 'rope',
        'cord', 'twine', 'ribbon', 'lace', 'trim',
        'fabric', 'cloth', 'textile', 'linen', 'cotton',
        'wool', 'silk', 'leather', 'hide', 'pelt',
        'fur', 'skin', 'feather', 'bone', 'horn',
        'antler', 'tusk', 'ivory', 'shell', 'pearl',
        'scale', 'claw', 'tooth', 'fang', 'venom',
        'poison', 'toxin', 'acid', 'chemical', 'compound',
        'mixture', 'solution', 'suspension', 'emulsion',
        'extract', 'essence', 'oil', 'tincture', 'infusion',
        'decoction', 'distillate', 'concentrate', 'isolate',
        'puree', 'paste', 'pulp', 'slurry', 'mud',
        'sludge', 'slime', 'gel', 'jelly', 'resin',
        'amber', 'copal', 'latex', 'sap', 'balsam',
        'ointment', 'salve', 'balm', 'cream', 'lotion',
        'poultice', 'compress', 'plaster', 'bandage',
        'dressing', 'gauze', 'cotton', 'wool', 'silk',
        'linen', 'hemp', 'jute', 'sisal', 'coir',
        'raffia', 'palm', 'bamboo', 'rattan', 'wicker',
        'willow', 'osier', 'reed', 'rush', 'sedge',
        'grass', 'straw', 'hay', 'chaff', 'husk',
        'hull', 'shell', 'pod', 'boll', 'burr',
        'spike', 'thorn', 'spine', 'prickle', 'sticker',
        'bur', 'cocklebur', 'foxtail', 'sandbur', 'sticktight',
        'hitchhiker', 'cleaver', 'goosegrass', 'bedstraw',
        'velcro plant', 'catchweed', 'stickywilly', 'stickyweed',
        'grip grass', 'loveman', 'sweethearts', 'clivers',
        'galium', 'rubia', 'asperula', 'valantia',
        'crucianella', 'sherardia', 'callipeltis', 'valantia'
    }
    
    def __init__(self, items_json_path: Optional[Path] = None):
        """Initialize the food parser.

        Args:
            items_json_path: Path to items.json. If None, uses default location.
        """
        if items_json_path is None:
            # Default location relative to this file
            items_json_path = Path(__file__).parent / 'data' / 'items.json'

        self.items_json_path = items_json_path
        self.items_data: Dict = {}
        self.food_items: Dict[str, FoodItem] = {}

        self._load_items()
        self._parse_foods()
    
    def _load_items(self):
        """Load items from JSON file."""
        try:
            with open(self.items_json_path, 'r', encoding='utf-8') as f:
                self.items_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"Error loading items.json: {e}")
            self.items_data = {}
    
    def _parse_foods(self):
        """Parse all edible food items from the loaded data."""
        for item_id, item_data in self.items_data.items():
            name = item_data.get('Name', '')
            
            # Skip if no name
            if not name:
                continue
            
            # Check if it's a food item
            if self._is_food_item(name, item_data):
                food = self._parse_food_item(item_id, item_data)
                if food:
                    self.food_items[item_id] = food
    
    def _is_food_item(self, name: str, item_data: Dict) -> bool:
        """Determine if an item is edible food.
        
        Args:
            name: Item name
            item_data: Full item data dictionary
            
        Returns:
            True if item appears to be edible food
        """
        name_lower = name.lower()
        internal_name = item_data.get('InternalName', '').lower()
        keywords = item_data.get('Keywords', [])
        description = item_data.get('Description', '').lower()
        
        # Check for non-food keywords first
        for non_food in self.NON_FOOD_KEYWORDS:
            if non_food in name_lower or non_food in internal_name:
                return False
        
        # Check for explicit food keywords
        for keyword in keywords:
            if keyword.lower() in ['food', 'edible', 'consumable', 'cookingredient']:
                return True
        
        # Check for food descriptors in name
        if self.DESCRIPTOR_PATTERN.search(name):
            return True
        
        # Check for food keywords in name
        for food_kw in self.FOOD_KEYWORDS:
            if food_kw in name_lower:
                return True
        
        # Check for "food" or "meal" in description
        if 'food' in description or 'meal' in description or 'eat' in description:
            return True
        
        return False
    
    def _parse_food_item(self, item_id: str, item_data: Dict) -> Optional[FoodItem]:
        """Parse a single food item from item data.
        
        Args:
            item_id: Item ID
            item_data: Full item data dictionary
            
        Returns:
            FoodItem object or None if parsing fails
        """
        name = item_data.get('Name', '')
        
        # Extract descriptors and base name
        descriptors = self.DESCRIPTOR_PATTERN.findall(name)
        base_name = self.DESCRIPTOR_PATTERN.sub('', name).strip()
        
        # Clean up extra spaces from descriptor removal
        base_name = re.sub(r'\s+', ' ', base_name).strip()
        
        return FoodItem(
            item_id=item_id,
            name=name,
            base_name=base_name,
            descriptors=[d.lower() for d in descriptors],
            internal_name=item_data.get('InternalName', ''),
            icon_id=item_data.get('IconId'),
            description=item_data.get('Description'),
            value=item_data.get('Value'),
            max_stack=item_data.get('MaxStackSize')
        )
    
    def get_all_foods(self) -> List[FoodItem]:
        """Get all parsed food items."""
        return list(self.food_items.values())
    
    def get_foods_by_descriptor(self, descriptor: str) -> List[FoodItem]:
        """Get all foods with a specific descriptor.
        
        Args:
            descriptor: Descriptor to filter by (e.g., 'meat', 'egg', 'dairy')
            
        Returns:
            List of FoodItem objects with the descriptor
        """
        descriptor_lower = descriptor.lower()
        return [f for f in self.food_items.values() if descriptor_lower in f.descriptors]
    
    def get_foods_by_descriptors(self, descriptors: List[str]) -> List[FoodItem]:
        """Get foods matching ANY of the provided descriptors.
        
        Args:
            descriptors: List of descriptors to filter by
            
        Returns:
            List of FoodItem objects matching at least one descriptor
        """
        descriptors_lower = [d.lower() for d in descriptors]
        return [
            f for f in self.food_items.values()
            if any(d in f.descriptors for d in descriptors_lower)
        ]
    
    def get_foods_by_name_contains(self, search: str) -> List[FoodItem]:
        """Search foods by name substring.
        
        Args:
            search: Search string
            
        Returns:
            List of FoodItem objects with matching names
        """
        search_lower = search.lower()
        return [
            f for f in self.food_items.values()
            if search_lower in f.name.lower() or search_lower in f.base_name.lower()
        ]
    
    def get_food_by_id(self, item_id: str) -> Optional[FoodItem]:
        """Get a specific food by its item ID."""
        return self.food_items.get(item_id)
    
    def get_all_descriptors(self) -> Set[str]:
        """Get all unique descriptors found in food items."""
        descriptors = set()
        for food in self.food_items.values():
            descriptors.update(food.descriptors)
        return descriptors
    
    def get_descriptor_counts(self) -> Dict[str, int]:
        """Get count of foods for each descriptor type."""
        counts = {}
        for food in self.food_items.values():
            for desc in food.descriptors:
                counts[desc] = counts.get(desc, 0) + 1
        return counts
    
    def export_food_list(self, output_path: Path) -> None:
        """Export the food list to a JSON file.
        
        Args:
            output_path: Path to save the JSON file
        """
        data = {
            'total_foods': len(self.food_items),
            'descriptors': sorted(self.get_all_descriptors()),
            'descriptor_counts': self.get_descriptor_counts(),
            'foods': [
                {
                    'id': f.item_id,
                    'name': f.name,
                    'base_name': f.base_name,
                    'descriptors': f.descriptors,
                    'internal_name': f.internal_name,
                    'icon_id': f.icon_id,
                    'description': f.description,
                    'value': f.value,
                    'max_stack': f.max_stack,
                    'has_meat': f.has_meat,
                    'has_egg': f.has_egg,
                    'has_dairy': f.has_dairy,
                    'has_vegetable': f.has_vegetable,
                    'has_fruit': f.has_fruit,
                    'has_grain': f.has_grain
                }
                for f in self.food_items.values()
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def get_foods_without_descriptors(self) -> List[FoodItem]:
        """Get foods that have no descriptors."""
        return [f for f in self.food_items.values() if not f.descriptors]
    
    def get_foods_with_multiple_descriptors(self, min_count: int = 2) -> List[FoodItem]:
        """Get foods with multiple descriptors.
        
        Args:
            min_count: Minimum number of descriptors (default 2)
            
        Returns:
            List of FoodItem objects with multiple descriptors
        """
        return [f for f in self.food_items.values() if len(f.descriptors) >= min_count]


# Convenience function for quick access
def parse_foods(items_json_path: Optional[Path] = None, use_cache: bool = True, refresh: bool = False) -> FoodParser:
    """Parse foods from items.json with caching support.
    
    Args:
        items_json_path: Optional path to items.json
        use_cache: Whether to use cached food list if available
        refresh: Force re-parse from JSON even if cache exists
        
    Returns:
        FoodParser instance with loaded food data
    """
    if items_json_path is None:
        items_json_path = Path(__file__).parent / 'data' / 'items.json'
    
    cache_path = Path(__file__).parent / 'data' / 'food_cache.json'
    
    # Try to load from cache first
    if use_cache and not refresh and cache_path.exists():
        try:
            # Check if cache is recent (less than 30 days old)
            import os
            cache_age_days = (os.path.getmtime(items_json_path) - os.path.getmtime(cache_path)) / (24 * 3600)
            
            # If items.json hasn't been modified since cache was created, use cache
            if cache_age_days < 0:  # cache is newer than items.json
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                
                parser = FoodParser.__new__(FoodParser)
                parser.items_json_path = items_json_path
                parser.items_data = {}
                parser.food_items = {}
                
                # Reconstruct FoodItem objects from cache
                for food_dict in cache_data.get('foods', []):
                    food = FoodItem(
                        item_id=food_dict['id'],
                        name=food_dict['name'],
                        base_name=food_dict['base_name'],
                        descriptors=food_dict['descriptors'],
                        internal_name=food_dict.get('internal_name', ''),
                        icon_id=food_dict.get('icon_id'),
                        description=food_dict.get('description'),
                        value=food_dict.get('value'),
                        max_stack=food_dict.get('max_stack')
                    )
                    parser.food_items[food.item_id] = food
                
                print(f"Loaded {len(parser.food_items)} foods from cache")
                return parser
        except Exception as e:
            print(f"Cache load failed, parsing from JSON: {e}")
    
    # Parse from JSON
    parser = FoodParser(items_json_path)
    
    # Save to cache for next time
    if use_cache:
        try:
            parser.export_food_list(cache_path)
            print(f"Saved {len(parser.food_items)} foods to cache")
        except Exception as e:
            print(f"Failed to save cache: {e}")
    
    return parser


def clear_food_cache():
    """Clear the food cache file to force re-parse on next load."""
    cache_path = Path(__file__).parent / 'data' / 'food_cache.json'
    if cache_path.exists():
        cache_path.unlink()
        print("Food cache cleared")


if __name__ == '__main__':
    # Test the parser
    parser = parse_foods()
    
    print(f"Total foods found: {len(parser.get_all_foods())}")
    print(f"\nAll descriptors found: {sorted(parser.get_all_descriptors())}")
    print(f"\nDescriptor counts:")
    for desc, count in sorted(parser.get_descriptor_counts().items(), key=lambda x: -x[1]):
        print(f"  {desc}: {count}")
    
    print(f"\nSample foods with descriptors:")
    for food in list(parser.food_items.values())[:10]:
        if food.descriptors:
            print(f"  {food.name} -> descriptors: {food.descriptors}")
    
    # Export to JSON
    output = Path(__file__).parent / 'parsed_foods.json'
    parser.export_food_list(output)
    print(f"\nExported food list to: {output}")
