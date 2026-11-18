# Franco-Arabic eval (2026-11-18T08:08:36+00:00)

## Run

| Field | Value |
|---|---|
| Provider | gemini |
| Model | `gemini-3.5-flash-lite` |
| Targets | detection: en (fr for en items); arabization: the item's label |
| Prompt fingerprints | en `2ac34465d2fb`, fr `f081acbcb4e6`, ar `6760617d77bd`, arz `572d36e53152` |
| Git commit | `2753347` |
| Dataset | `evals/data/franco.jsonl` (80 items) |
| Dataset sha256 | `5c5f40061ec0f355` |
| Filters | tag=-, split=-, limit=- |
| Items attempted / not run | 80 / 0 |
| Requests planned | 147 |
| Median latency | detect 897 ms, arabize 934 ms |

## Detection

**96.2%** (77/80), 95% Wilson CI 89.5% to 98.7%. Wrong: 3, errors: 0.

Control false positives (control detected as ar/arz): 0/13 = 0.0%, 95% Wilson CI 0.0% to 22.8%.

## Confusion matrix

| label \ predicted | arz | ar | en | fr | it | de | es | other | error |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **arz** | 61 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **ar** | 3 | 3 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **en** | 0 | 0 | 7 | 0 | 0 | 0 | 0 | 0 | 0 |
| **fr** | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 0 | 0 |
| **it** | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 |
| **de** | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| **es** | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 |

## Arabization

Mean chrF **84.9** over 67 successful output(s); Latin leak 1/67 = 1.5%. Errors (not scored): 0.

## Per split

| Group | n | Detection | Arabized (ok / errors) | Mean chrF | Latin leak |
|---|---:|---:|---:|---:|---:|
| dev | 53 | 98.1% (52/53) | 44 / 0 | 85.3 | 0.0% |
| test | 27 | 92.6% (25/27) | 23 / 0 | 84.2 | 4.3% |

## Per tag

| Group | n | Detection | Arabized (ok / errors) | Mean chrF | Latin leak |
|---|---:|---:|---:|---:|---:|
| ambiguous | 19 | 100.0% (19/19) | 17 / 0 | 91.3 | 0.0% |
| chat | 25 | 100.0% (25/25) | 18 / 0 | 82.6 | 5.6% |
| clear | 13 | 100.0% (13/13) | 13 / 0 | 97.9 | 0.0% |
| code_switch | 18 | 100.0% (18/18) | 18 / 0 | 52.0 | 5.6% |
| control | 13 | 100.0% (13/13) | 0 / 0 | n/a | n/a |
| long | 6 | 100.0% (6/6) | 6 / 0 | 91.0 | 0.0% |
| no_numerals | 21 | 100.0% (21/21) | 21 / 0 | 95.7 | 0.0% |
| numerals | 46 | 93.5% (43/46) | 46 / 0 | 80.0 | 2.2% |
| shared | 5 | 40.0% (2/5) | 5 / 0 | 100.0 | 0.0% |
| short | 13 | 84.6% (11/13) | 12 / 0 | 100.0 | 0.0% |

## Wrong and error detections (3)

| id | split | label -> predicted | text |
|---|---|---|---|
| f017 | test | ar -> arz | el7amdulellah |
| f029 | dev | ar -> arz | salamo 3aleko |
| f076 | test | ar -> arz | Sabah el kheir ya gama3a ☀️🌸 |

## Review: ar/arz items (67)

`arz output` is the `auto -> label` output (ar items go to ar). A `*` after chrF marks a Latin leak.

| id | text | arabic ref | arz output | chrF | en output | meaning |
|---|---|---|---|---:|---|---|
| f001 | ana msh fahem enta 3ayez eh | أنا مش فاهم إنت عايز إيه | أنا مش فاهم إنت عايز إيه | 100.0 | I don't understand what you want | I don't understand what you want |
| f002 | ezayak 3amel eh el naharda? | إزيك عامل إيه النهارده؟ | إزيك عامل إيه النهارده؟ | 100.0 | How are you doing today? | How are you doing today? |
| f004 | msh 3arfa a3mel eh dlwa2ty | مش عارفة أعمل إيه دلوقتي | مش عارفة أعمل إيه دلوقتي | 100.0 | I don't know what to do now. | I (f.) don't know what to do now |
| f005 | inshallah | إن شاء الله | إن شاء الله | 100.0 | God willing | God willing |
| f006 | ana mesh 3aref | أنا مش عارف | أنا مش عارف | 100.0 | I don't know | I don't know |
| f007 | enta fen? ana mstneek odam el beit | إنت فين؟ أنا مستنيك قدام البيت | إنت فين؟ أنا مستنيك قدام البيت | 100.0 | Where are you? I'm waiting for you in front of the house | Where are you? I'm waiting for you in front of the house |
| f008 | el meeting et2agel l bokra el sob7 | الـ meeting اتأجل لبكرة الصبح | الميتينج اتأجل لبكرة الصبح | 60.5 | The meeting was postponed to tomorrow morning. | The meeting was postponed to tomorrow morning |
| f009 | howa leh msh bayrod 3ala el phone? | هو ليه مش بيرد على الـ phone؟ | هو ليه مش بيرد على التليفون؟ | 72.0 | Why isn't he answering the phone? | Why isn't he answering the phone? |
| f011 | aayzeen nekhrog el gomaa di | عايزين نخرج الجمعة دي | عايزين نخرج الجمعة دي | 100.0 | We want to go out this Friday | We want to go out this Friday |
| f012 | mafeesh mashakel, bokra nkamel | مفيش مشاكل، بكرة نكمل | مافيش مشاكل، بكره نكمل | 92.7 | There are no problems, we'll continue tomorrow | No problem, we'll continue tomorrow |
| f013 | yalla bina | يلا بينا | يلا بينا | 100.0 | let's go | Let's go |
| f015 | m3lsh ya basha, 7asal 5er | معلش يا باشا، حصل خير | معلش يا باشا، حصل خير | 100.0 | Don't worry my friend, it's all for the best | Sorry man, no harm done |
| f016 | law enta fady kalemny | لو إنت فاضي كلمني | لو إنت فاضي كلمني | 100.0 | If you are free, call me. | If you're free, call me |
| f017 | el7amdulellah | الحمد لله | الحمد لله | 100.0 | Praise be to God | Praise be to God |
| f018 | bas ya3ni howa kan 3ayez eh mn el awel? | بس يعني هو كان عايز إيه من الأول؟ | بس يعني هو كان عاوز إيه من الأول؟ | 83.8 | Well, what did he actually want from the beginning? | But what did he want from the start? |
| f019 | isa nt2abl bokra | إن شاء الله نتقابل بكرة | إن شاء الله نتقابل بكره | 100.0 | God willing, we will meet tomorrow | Hopefully we'll meet tomorrow |
| f020 | el gaw harr awy enaharda | الجو حر أوي النهارده | الجو حار أوي النهارده | 80.0 | The weather is very hot today | The weather is very hot today |
| f022 | gaay fl tare2 | جاي في الطريق | جاي في الطريق | 100.0 | Coming on the way | I'm on my way |
| f023 | kont fakrak msafer. rg3t emta? w leh mesh 2oltly? | كنت فاكرك مسافر. رجعت إمتى؟ وليه مش قلتلي؟ | كنت فاكرك مسافر. رجعت إمتى؟ و ليه مش قلتلي؟ | 100.0 | I thought you were traveling. When did you come back? And why didn't you tell me? | I thought you were travelling. When did you get back? And why didn't you tell me? |
| f024 | ahhhh ana ta3baaaan awy | آه أنا تعبان أوي | آآآه أنا تعبااان أوي | 75.6 | Ahhhh I am so tired | Ugh, I'm so tired |
| f025 | el internet wa2e3 tany, msh 3aref a3mel upload | الـ internet واقع تاني، مش عارف أعمل upload | النت قاطع تاني، مش عارف أرفع حاجة | 34.6 | The internet is down again, I can't upload anything. | The internet is down again, I can't upload |
| f027 | eh el akhbar? | إيه الأخبار؟ | إيه الأخبار؟ | 100.0 | What's the news? | What's new? |
| f028 | khalas, ana hakallemak ba3d el shoghl | خلاص، أنا هكلمك بعد الشغل | خلاص، أنا هكلمك بعد الشغل | 100.0 | Okay, I'll call you after work. | OK, I'll call you after work |
| f029 | salamo 3aleko | السلام عليكم | السلام عليكم | 100.0 | peace be upon you | Peace be upon you (hello) |
| f030 | mama bet'olak taala etghada maana | ماما بتقولك تعالى اتغدى معانا | ماما بتقولك تعالى اتغدى معانا | 100.0 | Mom tells you to come have lunch with us | Mom says come have lunch with us |
| f031 | fi 7aga? | في حاجة؟ | في حاجة؟ | 100.0 | Is there something wrong? | Is something wrong? |
| f032 | enta feen ya 3am? ba2alak sa3a mesh bterod | إنت فين يا عم؟ بقالك ساعة مش بترد | إنت فين يا عم؟ بقالك ساعة مش بترد | 100.0 | Where are you, man? You haven't been answering for an hour. | Where are you, man? You haven't answered for an hour |
| f033 | momken teb3atly el file el naharda? | ممكن تبعتلي الـ file النهارده؟ | ممكن تبعتلي الملف النهاردة؟ | 69.6 | Can you send me the file today? | Can you send me the file today? |
| f035 | lessa makhalastesh el shoghl | لسه ماخلصتش الشغل | لسه ماخلصتش الشغل | 100.0 | I haven't finished the work yet. | I still haven't finished work |
| f036 | izayak ya sahby, wahashtny | إزيك يا صاحبي، وحشتني | إزيك يا صاحبي، وحشتني | 100.0 | How are you my friend, I missed you | How are you, buddy? I missed you |
| f037 | kda kda msh hanl72 | كده كده مش هنلحق | كده كده مش هنلحق | 100.0 | We won't make it anyway. | We won't make it anyway |
| f039 | ana aayez akol haga helwa | أنا عايز آكل حاجة حلوة | أنا عايز آكل حاجة حلوة | 100.0 | I want to eat something sweet | I want to eat something sweet |
| f040 | mish fahma leh el doktor 2al keda | مش فاهمة ليه الدكتور قال كده | مش فاهمة ليه الدكتور قال كدة | 100.0 | I don't understand why the doctor said that. | I (f.) don't understand why the doctor said that |
| f041 | la a3rif madha turid | لا أعرف ماذا تريد | لا أعرف ماذا تريد | 100.0 | I do not know what you want | I don't know what you want |
| f042 | wallahy ma3rafsh | والله ماعرفش | والله ماعرفش | 100.0 | I swear I don't know | I swear I don't know |
| f043 | el moslsal kan helw awy bas el nehaya wehsha | المسلسل كان حلو أوي بس النهاية وحشة | المسلسل كان حلو أوي بس النهاية وحشة | 100.0 | The series was very nice but the ending was bad | The series was really good but the ending was bad |
| f044 | khod balak men nafsak ya habibi. w matensash tekalemny lama tewsal | خد بالك من نفسك يا حبيبي. وماتنساش تكلمني لما توصل | خود بالك من نفسك يا حبيبي. وماتنساش تكلمني لما توصل | 97.2 | Take care of yourself, my love. And don't forget to call me when you arrive. | Take care of yourself, dear. And don't forget to call me when you arrive |
| f045 | rayheen el sahel el weekend da | رايحين الساحل الـ weekend ده | رايحين الساحل الويك إند ده | 58.6 | We are going to the North Coast this weekend | We're going to the North Coast this weekend |
| f047 | ana 3ayez a2olak 7aga mohema bas mtz3alsh | أنا عايز أقولك حاجة مهمة بس متزعلش | أنا عايز أقولك حاجة مهمة بس متزعلش | 100.0 | I want to tell you something important, but don't get upset. | I want to tell you something important, but don't be upset |
| f048 | ent btkalem meen? | إنت بتكلم مين؟ | إنت بتكلم مين؟ | 100.0 | Who are you talking to? | Who are you talking to? |
| f049 | el sha2a di ghalya awy. mafish 7aga ar5as fl mante2a di? | الشقة دي غالية أوي. مفيش حاجة أرخص في المنطقة دي؟ | الشقة دي غالية أوي. مافيش حاجة أرخص في المنطِقة دي؟ | 92.2 | This apartment is very expensive. Isn't there anything cheaper in this area? | This flat is very expensive. Isn't there anything cheaper in this area? |
| f051 | dilwa'ti mesh wa2to, ba3den nshoof | دلوقتي مش وقته، بعدين نشوف | دلوقتي مش وقته، بعدين نشوف | 100.0 | Now is not the time, we'll see later. | Now is not the time, we'll see later |
| f052 | please ya gama3a, el report lazem yetsallem bokra w mafeesh ay ta2gil. kol wa7ed yeb3at goz2o el leila di | please يا جماعة، الـ report لازم يتسلم بكرة ومفيش أي تأجيل. كل واحد يبعت جزءه الليلة دي | يا جماعة لو سمحتم، التقرير لازم يتسلم بكره ومفيش أي تأجيل. كل واحد يبعت جزؤه الليلة دي | 70.0 | Please everyone, the report has to be delivered tomorrow and there is no postponement. Everyone should send their part tonight. | Please, guys, the report must be handed in tomorrow with no delay. Everyone send your part tonight |
| f053 | ramadan kareem | رمضان كريم | رمضان كريم | 100.0 | Ramadan Kareem | Have a blessed Ramadan |
| f054 | enta el ahsan | إنت الأحسن | إنت الأحسن | 100.0 | You are the best | You're the best |
| f055 | nfsy asafer barra bs msh ma3aya budget | نفسي أسافر برة بس مش معايا budget | نفسي أساور برة بس مش معايا ميزانية | 60.1 | I want to travel abroad, but I don't have the budget. | I'd love to travel abroad but I don't have the budget |
| f056 | el kahraba et2ata3et men el sob7, w el talaga ba2et sokhna. mesh 3arfeen nesta7ama 7atta | الكهربا اتقطعت من الصبح، والتلاجة بقت سخنة. مش عارفين نستحمى حتى | الكهربا اتقطعت من الصبح، والثلاجة بقت سخنة. مش عارفين نستحما حتى | 86.7 | The electricity has been cut off since the morning, and the fridge has gotten warm. We can't even take a shower. | The power has been out since morning and the fridge got warm. We can't even shower |
| f057 | ya3ni a3mel eh dlwa2ti? kolo baz | يعني أعمل إيه دلوقتي؟ كله باظ | يعني أعمل إيه دلوقتي؟ كله باظ | 100.0 | So what should I do now? Everything is ruined. | So what do I do now? Everything is ruined |
| f059 | howa da el charger elly kont 3ayzo | هو ده الـ charger اللي كنت عايزه | هو ده الشاحن اللي كنت عاوزه | 46.8 | This is the charger I wanted. | That's the charger I wanted |
| f060 | ehna fel beit, taala ay wa't | إحنا في البيت، تعالى أي وقت | إحنا في البيت، تعالي أي وقت | 100.0 | We are at home, come anytime. | We're at home, come any time |
| f061 | Ana msh 3aref a3mel eh b7d 😭😭 | أنا مش عارف أعمل إيه بجد 😭😭 | أنا مش عارف أعمل إيه بجد 😭😭 | 100.0 | I don't know what to do with anyone 😭😭 | I really don't know what to do |
| f062 | I'm so ta3ban today wallahy 😩 | I'm so تعبان today والله 😩 | أنا تعبان أوي النهاردة وربنا 😩 | 17.6 | I'm so tired today honestly 😩 | I am so tired today I swear |
| f063 | Hwa el meeting sa3a kam??? | هو ال meeting ساعة كام؟؟؟ | هو الاجتماع الساعة كام؟ | 37.5 | What time is the meeting? | What time is the meeting? |
| f064 | 7a2olak 3ala 7aga bas mat2olsh l 7ad 🤫 | هقولك على حاجة بس متقولش لحد 🤫 | هأقولك على حاجة بس ماتقولش لحد 🤫 | 82.2 | Let me tell you something, but don't tell anyone 🤫 | I will tell you something just don't tell anyone |
| f065 | H3mklk call f 10 da2ay2 ISA | هعملك call في 10 دقايق إن شاء الله | هكلمك كول في 10 دقايق إن شاء الله | 66.1 | I will call you in 10 minutes, God willing | I will call you in 10 minutes God willing |
| f066 | El jaw elnhrda 7r awyyyy 🥵☀️ | الجو النهاردة حر أوي 🥵☀️ | الجو النهاردة حر أوي 🥵☀️ | 100.0 | The weather is very hot today 🥵☀️ | The weather today is very hot |
| f067 | Let's go nakol 7aga, ana ga3an موت 😂 | Let's go ناكل حاجة، أنا جعان موت 😂 | يلا بينا ناكل حاجة، أنا جعان موت 😂 | 72.5 | Let's go grab a bite, I'm dying of hunger 😂 | Let's go eat something, I am starving |
| f068 | Kont 3ayz as'al 3la el2as3ar لو سمحت | كنت عايز أسأل على الأسعار لو سمحت | كنت عايز أسأل ع الأسعار لو سمحت | 82.4 | I wanted to ask about the prices, please | I wanted to ask about the prices please |
| f069 | Tyb tmm hstnak hnak 👍 | طيب تمام هستناك هناك 👍 | طيب تمام ه استناك هناك 👍 | 81.4 | Okay perfect, I will wait for you there 👍 | Okay great I will wait for you there |
| f070 | Msh 2ader asada' en el weekend 5alas 5eles 😭!!! | مش قادر أصدق إن ال weekend خلاص خلص 😭!!! | مش قادر أصدق إن الويك إند خلاص خلص 😭!!! | 64.1 | I can't believe the weekend is already over 😭!!! | I can't believe the weekend is already over |
| f071 | Enta fen yaba b2aly 2 hours مستنيك 😡!! | إنت فين يابا بقالي 2 hours مستنيك 😡!! | إنت فين يابا بقالي ساعتين مستنيك 😡!! | 66.1 | Where are you, man? I've been waiting for you for 2 hours 😡!! | Where are you bro I've been waiting for 2 hours |
| f072 | Btw el T-shirt da to7fa 3alek 🔥😍 | Btw ال T-shirt دا تحفة عليك 🔥😍 | Btw el T-shirt da to7fa 3alek 🔥😍 | 22.8 * | Btw this T-shirt looks amazing on you 🔥😍 | By the way this T-shirt looks amazing on you |
| f073 | Bro the server went down 3 marrat today, msh ma32ool 💀 | Bro the server went down 3 مرات today، مش معقول 💀 | يا عم السيرفر وقع 3 مرات النهاردة، مش معقول 💀 | 22.5 | Bro the server went down 3 times today, unbelievable 💀 | Bro the server went down 3 times today, unbelievable |
| f074 | Ma3lesh I forgot a-send el file embare7 🤦‍♂️ | معلش I forgot أ-send ال file امبارح 🤦‍♂️ | معلش نسيت أبعت الملف إمبارح 🤦‍♂️ | 33.8 | Sorry I forgot to send the file yesterday 🤦‍♂️ | Sorry I forgot to send the file yesterday |
| f075 | Yalla b2a 3shan m2t5rsh 3la el cinema 🏃‍♂️💨 | يلا بقى عشان منتأخرش على ال cinema 🏃‍♂️💨 | يلا بقى عشان ماأتأخرش على السينما 🏃‍♂️💨 | 60.4 | Come on now so I'm not late for the cinema 🏃‍♂️💨 | Let's go so we don't get late for the cinema |
| f076 | Sabah el kheir ya gama3a ☀️🌸 | صباح الخير يا جماعة ☀️🌸 | صباح الخير يا جماعة ☀️🌸 | 100.0 | Good morning everyone ☀️🌸 | Good morning everyone |
| f077 | Alf mabrouk el tagharog, عقبال الماجستير 🎓🎉 | ألف مبروك التخرج، عقبال الماجستير 🎓🎉 | ألف مبروك التخرج، عقبال الماجستير 🎓🎉 | 100.0 | Congratulations on the graduation, looking forward to your Master's degree 🎓🎉 | Congratulations on graduating, wishing you a master's degree next |

## Review: controls (13)

| id | text | label -> predicted | output |
|---|---|---|---|
| f003 | lol I'm so tired, see you tomorrow | en -> en | mdr je suis trop fatigué, à demain |
| f010 | Je suis en retard, désolé, j'arrive dans dix minutes | fr -> fr | I am late, sorry, I will be there in ten minutes |
| f014 | law school is so hard, I barely sleep | en -> en | L'école de droit est si difficile, je dors à peine. |
| f021 | jaja no puedo más, nos vemos mañana | es -> es | haha I can't take it anymore, see you tomorrow |
| f026 | ciao, a dopo | it -> it | hi, see you later |
| f034 | the mesh wifi keeps dropping, any fix? | en -> en | Le Wi-Fi maillé n'arrête pas de couper, y a-t-il une solution ? |
| f038 | bin gleich da, warte kurz | de -> de | almost there, wait a second |
| f046 | mdr t'es où ? on t'attend | fr -> fr | lol where are you? we're waiting for you |
| f050 | no sé si puedo ir, te aviso luego | es -> es | I don't know if I can go, I'll let you know later |
| f058 | brb gonna grab food, ttyl | en -> en | Je reviens, je vais manger, à plus tard |
| f078 | Can you send me the 2nd report b4 3pm pls?? | en -> en | Peux-tu m'envoyer le 2e rapport avant 15h stp ?? |
| f079 | lmk if u r free 2mrw @ 8!! | en -> en | tiens-moi au courant si tu es libre demain à 20h !! |
| f080 | I bought 3 tickets 4 the show tonight 🎉 | en -> en | J'ai acheté 3 billets pour le spectacle de ce soir 🎉 |
