import json, os

paragraph = (
    "A monthly procurement-card transaction listing headed \"TROY SCHOOL DISTRICT, PCARD report, "
    "May 2026,\" carried on the Troy Board of Education agenda for the meeting dated 2026-07-22 and "
    "bearing the print date 7/9/26 in its page footers. Across 20 pages it itemizes every card "
    "purchase by transaction date, merchant description, journal-entry label (\"MAY 2026 PCARD\"), "
    "combined business-unit/account code, and amount, with activity dated from 04/24/26 through "
    "05/29/26. The listing closes with a single grand total of 374,998.51. The two largest line "
    "items are BIGSIGNS.COM, INC. charges of 22,070.00 and 21,804.00, both posted 05/19/26 to "
    "codes 4230704560000006410 and 4230714560000006410."
)

page_lines = [
    "**What it is**",
    "A line-item procurement-card (P-Card) transaction register for Troy School District covering May 2026, presented to the Board of Education on the agenda dated 2026-07-22. The printed report runs 20 pages and carries the print date 7/9/26 in each page footer.",
    "",
    "**Format**",
    "Column headings repeat on each page: Date, Transaction Description, J E descrip, B.U.# Account, Amount. Every row carries the identical journal-entry description \"MAY 2026 PCARD.\" Business-unit and account codes print as one concatenated string prefixed with \"PCARD\" (for example PCARD7000703999900005000, PCARD5292023916600007919). Transaction dates run 04/24/26 through 05/29/26, so late-April charges appear in the May cycle. Credits print in parentheses; one row, MICHAELS #9490 on 05/18/26, shows a dash in the amount column.",
    "",
    "**Grand total**",
    "374,998.51",
    "",
    "**Largest single charges**",
    "",
    "| Date | Merchant | Code | Amount |",
    "| --- | --- | --- | --- |",
    "| 05/19/26 | IN BIGSIGNS.COM, INC. | 4230704560000006410 | 22,070.00 |",
    "| 05/19/26 | IN BIGSIGNS.COM, INC. | 4230714560000006410 | 21,804.00 |",
    "| 04/30/26 | BIANCO TOURS, INC. | 7000532997000005000 | 8,391.41 |",
    "| 05/18/26 | IN STUKENT, INC. | 1010701275210003450 | 7,890.00 |",
    "| 05/11/26 | FESTIVALS OF MUSIC | 7000522993520005000 | 7,416.00 |",
    "| 05/18/26 | IN STUKENT, INC. | 1010711275210003450 | 7,190.00 |",
    "| 05/28/26 | PAY YMCA STORER CAMPS | 7000141993930005000 | 6,635.20 |",
    "| 05/14/26 | THINGSREMEMBERED.COM | 1017002830867005990 | 6,169.99 |",
    "| 05/23/26 | AMAZON MARK W90668YR3 | 4231602250000006410 | 5,487.02 |",
    "| 05/26/26 | GILBERT SALES SERVICE | 1010701270210005110 | 5,400.00 |",
    "| 05/28/26 | PAY YMCA STORER CAMPS | 7000141993930005000 | 5,000.00 |",
    "| 05/27/26 | GLF GREYSTONEGOLFCLUB | 7000713999920005000 | 4,590.00 |",
    "| 05/11/26 | PP TROY HISTORICAL SOC | 7000522997088005000 | 4,528.00 |",
    "| 05/13/26 | BLUE LAKES CHARTERS | 7000512993715005000 | 4,497.94 |",
    "| 05/14/26 | PP TROY HISTORICAL SOC | 7000532996672005000 | 4,480.00 |",
    "| 05/07/26 | SIX FLAGS AR | 7000512993715005000 | 4,350.24 |",
    "| 05/27/26 | B AND R SPORTING GOODS | 1010161111001005110 | 4,011.00 |",
    "| 05/21/26 | CARRS MOTORCOACH LLC | 1010712717325004230 | 3,800.00 |",
    "| 05/18/26 | GORDON FOOD SERVICE | 7000713997374005000 | 3,305.52 |",
    "| 05/13/26 | Scholastic, Inc. | 7000111997080005000 | 3,248.40 |",
    "",
    "**Excursion and venue vendors**",
    "PP TROY HISTORICAL SOC also appears at 2,880.00 and 225.00. HF MUSEUM CALL CENTER charges run 1,458.00, 1,280.00, 1,274.00, 1,176.00 and 1,134.00 plus a (72.00) credit; DETROIT ZOO-GUEST RELA 1,095.00, 1,007.00, 981.00, 843.00 and 795.00; MI Science Center 1,175.00; JFI URBAN AIR STERLING 2,406.50, 1,254.00 and 1,158.00; TST ZAP ZONE 2,699.30; SQ UPLAND HILLS FARM 846.00 and 770.00; PY BLAKES ORCHARD INC 900.00; DETROIT PUBLIC THEATRE 1,515.00; and four ALLSTAR CHAUFFEURED SV charges of 1,178.10 each.",
    "",
    "**Software and subscriptions**",
    "ANTHROPIC: CLAUDE TEAM posted three charges on 05/21/26: 1,680.00 and 239.95 to 1017902840000003450 and 720.00 to 1016682520668007910. OPENAI CHATGPT SUBSCR posted 20.00 on 05/08/26, 20.00 on 05/09/26, 20.00 on 05/10/26 and 119.88 on 05/23/26. Other technology items include FORTE 780.00, VMO VIMEO.COM 300.00, CCI CONSTANT-CONTACT 335.00, TYPEFORM 129.00, KAHOOT! ASA 95.09, ZOOM.COM 16.99 and Spotify 12.99.",
    "",
    "**Fleet and utilities (5292 codes)**",
    "PEPBOYS STORE # 6563 2,189.72; MICHIGAN WORKS| ASSOCI 2,140.00; AVON RADIATOR REPAIR 1,269.83; MASTER RADIATOR 1,172.08; CALLAHAN`S MUFFLER AND 720.00; BELLE TIRE 029 700.00; MICLOUDBYRINGCENTRAL 696.43; PERRY STREET AUTO 525.23; DTE RESIDENTIAL 500.00; COMCAST / XFINITY 351.28; AT&T PAYMENT 46.47.",
    "",
    "**Credits and disputes**",
    "A row dated 04/24/26 reads FRAUD DISPUTE for 1,224.00 against 7000532997000005000. Parenthesized credits include GRADUATE EAST LANSING (438.64), GRAND TRAVERSE RESORT (438.97), FSP MISSION POINT (361.81), MICHIGAN WORKS| ASSOCI (350.00), PAY ZEHNDER S BANQUETS (320.00), DISCOUNTSCH (265.16), PAYPAL MIHOSA (257.50), AMAZON MKTPLACE PMTS (134.99), JIMMY JOHNS 9031 (125.02), SPIRIT AI (100.09) and WOODCRAFT 321 (59.96).",
]
page = "\n".join(page_lines)

verbose_lines = [
    "**Identification and format**",
    "A procurement-card expenditure register headed \"TROY SCHOOL DISTRICT, PCARD report, May 2026,\" filed on the Troy School District Board of Education agenda dated 2026-07-22 under the title \"11 May 2026 P Card Report.\" The report is 20 pages long; each page repeats the banner line, the column headings \"Date / Transaction Description / J E descrip / B.U.# Account / Amount,\" a page number, and the print date 7/9/26. Every transaction row carries the same journal-entry description, \"MAY 2026 PCARD,\" followed immediately by a concatenated business-unit and account string (rendered in the extraction as, for example, PCARD7000703999900005000, PCARD1010141111001005110, PCARD5292023916600007919, PCARD4231602250000006410). Posting dates span 04/24/26 through 05/29/26, so a group of late-April charges is swept into the May cycle. Credit and refund amounts are shown in parentheses. One line, MICHAELS #9490 on 05/18/26 against 1010701130070005110, prints a dash rather than a figure. The register concludes with a single grand total of 374,998.51 on the final page.",
    "",
    "**Highest-value line items**",
    "Two charges to IN BIGSIGNS.COM, INC. dated 05/19/26 dominate the month: 22,070.00 against 4230704560000006410 and 21,804.00 against 4230714560000006410. Other large items include BIANCO TOURS, INC. 8,391.41 (04/30/26, 7000532997000005000); IN STUKENT, INC. 7,890.00 (1010701275210003450) and 7,190.00 (1010711275210003450), both 05/18/26; FESTIVALS OF MUSIC 7,416.00 (05/11/26, 7000522993520005000); three PAY YMCA STORER CAMPS charges on 05/28/26 of 6,635.20, 5,000.00 and 1,635.20, all to 7000141993930005000; THINGSREMEMBERED.COM 6,169.99 (05/14/26, 1017002830867005990); AMAZON MARK W90668YR3 5,487.02 and AMAZON MARK 1X3UL7ET3 2,612.90, both to 4231602250000006410; GILBERT SALES SERVICE 5,400.00 and SOI SNAP-ON INDUSTRIAL 1,510.16, both to 1010701270210005110; GLF GREYSTONEGOLFCLUB 4,590.00 and 4UP FIELDSTONE GC 2,816.00 to 7000713999920005000; BLUE LAKES CHARTERS 4,497.94 and 187.41 plus SIX FLAGS AR 4,350.24 to 7000512993715005000; B AND R SPORTING GOODS 4,011.00 (1010161111001005110); CARRS MOTORCOACH LLC 3,800.00 (1010712717325004230); GORDON FOOD SERVICE 3,305.52 (7000713997374005000) and 325.40 (1010711275441005990).",
    "",
    "**Troy Historical Society, museums, zoos and excursions**",
    "PP TROY HISTORICAL SOC appears four times: 4,528.00 (05/11/26, 7000522997088005000), 4,480.00 (05/14/26, 7000532996672005000), 2,880.00 (05/12/26, 7000502997000005000) and 225.00 (05/04/26, 7000171993930005000). HF MUSEUM CALL CENTER charges are 1,458.00, 1,280.00, 1,274.00, 1,176.00 and 1,134.00, with a (72.00) credit on 05/20/26. DETROIT ZOO-GUEST RELA charges are 1,095.00, 1,007.00, 981.00, 843.00, 795.00, 108.00 and 9.00. MI Science Center billed 1,175.00, 50.00 and 42.00 to 7000161997194005000; MI MUSEUM ADMISSIONS billed 432.00 and 396.00. TST ZAP ZONE posted 2,699.30 on 05/29/26. JFI URBAN AIR STERLING posted 2,406.50, 1,254.00, 1,158.00 twice, and 254.99 several times. Other venue and outing vendors include SQ UPLAND HILLS FARM 846.00 and 770.00, PAY YMCA CAMP COPNECON 803.40, PY BLAKES ORCHARD INC 900.00, COOK'S FARM DAIRY INC 562.50, BOWERS FARM AND JOHNSO 536.00, TROYNATURE 609.43, 407.55, 297.17, 36.57, 24.45 and 17.83, SQ ESCAPE ENTERTAINME 620.40, 372.00, 84.89, 39.60 and 5.41, DETROIT PUBLIC THEATRE 1,515.00, PISTONS SPORTS & ENT 200.00, THE AMERICAN POLISH CU 1,826.77, DIAMOND JACKS RIVER TO 825.00, Sky Zone Commerce Town 549.75, PLAYPLACE F 155.00, SlickCityTroy 135.00, TAMARACK CAMPS 257.50 twice, TST TOPGOLF - AUBURN 160.00, UMD ENV INTERPRETIVE C 180.00, SQ CORNERSTONES OF CA 1,300.00 and I2G Quest Transportati 1,500.00. Four ALLSTAR CHAUFFEURED SV charges of 1,178.10 each posted 05/11/26 to 7000141993930005000.",
    "",
    "**Instructional materials, publishers and supplies**",
    "Scholastic, Inc. posted 3,248.40 (7000111997080005000), 2,638.88 (7000071997080005000), 1,753.93 (7000512997080005000) and 1,242.34 (7000502997080005000). Other curriculum and supply vendors include ProLiteracy Worldwide 920.80, TOWNSEND PRESS INC 505.88, CAMBRIDGE UNIV PRESS 647.00 and 19.52, SUPER DUPER PUBLICATIO 237.68, 38.94, 19.95 and a (12.73) credit, SP BJOREM SPEECH 238.75, ULTIMATE SLP 12.95, SCHOOLMART 921.16, SCHOOL SPECIALTY ECOMM 293.13, DISCOUNTSCH charges of 250.16, 265.16 and 15.00 with a (265.16) credit, LAKESHORE LEARNING 467.31 and 59.97, REALLY GOOD STUFF 118.90 and 7.54, MEAD PRODUCTS LLC 249.36 and 14.96, ACCO BRANDS DIRECT 129.42 and 6.96 twice, SMART BUSINESS SOURCE 1,304.24, IMAGESTUFF.COM 504.51 and 36.57, RUNYAN POTTERY SUPPLY 327.50, DBC BLICK ART MATERIAL 143.98, J.W. PEPPER 29.99, SHAR MUSIC 80.10, NATIONAL SCIENCE TEACH 30.00, MEMORYPROJECT.ORG 180.00, THRIFT BOOKS GLOBAL 126.16 and SP LITTLEFREELIBRARY 643.60. MARSHALL MUSIC #2 posted 1,773.74, 289.97, 215.00, 108.00, 90.00 and 42.68. Twelve building codes (1010051110425005110 through 1010171110425005110) each received a 25.50 AMAZON MKTPL BV6G17KP2 charge on 05/03/26 and a VENTRIS LE charge on 05/05/26 of 188.12 or 188.13. GOPHER FAMILY BRANDS billed 1,574.00 twice and AMAZON MARK billed 1,037.40 twice against the 130425 codes.",
    "",
    "**Technology, software and professional subscriptions**",
    "ANTHROPIC: CLAUDE TEAM posted three charges dated 05/21/26: 1,680.00 and 239.95 to 1017902840000003450, and 720.00 to 1016682520668007910. OPENAI CHATGPT SUBSCR posted 20.00 on 05/08/26 (7009706999900005000), 20.00 on 05/09/26 (1019282820000003450), 20.00 on 05/10/26 (1010711130071007410) and 119.88 on 05/23/26 (1019022618499004140). FORTE billed 780.00 to 1017902250000003450. Additional subscription and service charges include CCI CONSTANT-CONTACT 335.00, VMO VIMEO.COM 300.00, TYPEFORM 129.00, KAHOOT! ASA 95.09, ZOOM.COM 16.99, Spotify 12.99, EDPUZZLE PRO TEACHER 15.00 on three occasions, HEARTLAND POS 419.42, G2GCHARGE COM SERVICE 20.37, DAKTRONICS 656.25, HAAS AUTOMATION 670.91, US.STORE.BAMBULAB.COM 1,268.82 and 845.88, B&H PHOTO 845.86 and ULINE SHIP SUPPLIES 2,336.00 and 525.00.",
    "",
    "**Conferences, travel and lodging**",
    "PARK PLACE HOTEL charges against 1202062216018003220 comprise 271.10 on 05/01/26 and repeated 563.77 charges on 05/01/26 and 05/02/26. GRAND TRAVERSE RESORT charges against 1016682850000003220 are 588.97, 602.97, 245.45, 409.45, 409.45 and 581.65, with credits of (438.97) and (179.52). HOMEWOOD SUITES posted six charges of 162.37 to 1203152216846003220. FSP MISSION POINT posted 315.01 and 355.01 with credits of (40.00) and (361.81); SHEPLERS MACKINAC ISLA 50.00 and MACKINAC ISLAND CARRIA 9.43 and 0.57 accompany them. Other travel items include MASB 999.00, CROWNE PLAZA LANSING 174.90, RADISSON PLAZA HOTEL A 615.33 twice, HAMPTON INNS 1,064.65, OMNI SEVERIN 1,025.11, BOYNE MTN LODGING 215.23, TREETOPS - H LODGING 176.60, HERTZ CAR RENTAL 485.97 and 85.03, SOUTHWES 231.40, METRO AIRPORT PARKING 90.33, UW MADISON SOE PLACE 695.00, UTC CONTINUING EDUCATI 799.00, UNC CHAR AACOED STEM I 750.00, REFLECTIVEWISDOM.COM 636.00, IIRP ESSENTIAL TRAINI 225.00, ASSOCIATION FOR CAREER 275.00, EDGE MDE MDE-OCTE: FA 300.00, KL NRF RISEUP 1,595.00, MICHIGAN SCHOOL BUSINE 450.00 and 60.00, MW GENESEE ISD 225.00, SQ OAKLAND COUNTY COM 70.00, PSI EXAMS 196.00 and PAYPAL ANGIE.ALLEN.E1 360.00. NHA charges of 165.00 recur across 1012001350945803190, 1202041350945803190 and 1202151350945803190.",
    "",
    "**Fleet, utilities and operations**",
    "Charges routed to 5292 codes include PEPBOYS STORE # 6563 2,189.72, MICHIGAN WORKS| ASSOCI 2,140.00, AVON RADIATOR REPAIR 1,269.83, MASTER RADIATOR 1,172.08, CALLAHAN`S MUFFLER AND 720.00, BELLE TIRE 029 700.00, MICLOUDBYRINGCENTRAL 696.43, PERRY STREET AUTO 525.23, DTE RESIDENTIAL 500.00, COMCAST / XFINITY 351.28, 4TE CULLIGAN OF ANN AR 52.53, AT&T PAYMENT 46.47 and KROGER #463 8.47. Elsewhere, SUNOCO 0830259800 billed 125.76, WILLIAMS DIS SOUTHFIEL 112.80, TURNER SANITATION INC billed 150.00 twice, IN MICHIANA TIMING 371.00, C &G PUBLISHING INC 355.00 and OAKLAND COUNTY MI 582.00. Vehicle-service charges to 1010701275791005110 include SUBURBAN CADILLAC OF T 281.84 and 95.53, MOTOWN AUTOMOTIVE 46.75 and MAXI AUTO 545 TROY entries of 55.19, 55.19 and 32.89 offset by credits of (55.19) twice and (32.89).",
    "",
    "**Food, catering and food service**",
    "GORDON FOOD SERVICE, GFS STORE #1907, GFS STORE #0947, GFS STORE #0960 and GFS ecomm appear repeatedly; COSTCO DELIVERY #1663 posted 321.58, 214.42, 158.80 and 105.32; SQ ATLAS WHOLESALE FO posted 992.32 and 689.76; PAY ZEHNDER S BANQUETS posted 670.00, 595.00 and 350.00 with a (320.00) credit; CONDADO TACOS 697.62; EZCATER CITY BARBEQUE 485.22; BREAKAWAY DELI 481.47, 55.07 and 52.15; PANERA BREAD charges of 442.53, 161.44, 114.72, 110.25, 52.11, 9.68 and 6.61 with a (21.49) credit; CHIPOTLE ONLINE 442.02 and 266.86; QDOBA 1719 ONLINE 405.45; SQ CARPEN FARMS 569.75 and 31.50; VARSITYSWEATER.COM 945.00; and numerous KROGER, MEIJER, SAMS CLUB, WALMART, DOLLAR TREE, BENITO S PIZZA OF TROY, PAPA ROMANOS, LITTLE CAESARS, JIMMY JOHNS, KRISPY KREME and STARBUCKS entries. Food-service supply codes beginning 53100411862 carry many small AMAZON, DISCOUNTSCH and MEAD PRODUCTS purchases.",
    "",
    "**Signage, apparel, awards and printing**",
    "SIGNS & MORE billed 1,500.00, 910.00, 550.00, 350.00, 220.00, 175.00, 110.00 and 75.00. JOSTENS INC. billed 2,873.62, 1,612.72 and 20.60. SQ MITCH'S PRINTS billed 1,626.00 and 99.00. IN TAG SPORTS GRAPHIC 780.89 and SP ATHLETESTHREAD.COM 130.58 accompany AMAZON MKTPL OD4TA4KU3 charges of 750.00 and 45.00 to 7000703999020005000. FAMS T-SHIRTS & DESIGN billed 709.30, PDQ PRINTING 655.00, PRINTASTIC.COM 400.00, SIGNARAMA TROY 309.00, VSN PHOTO 510.00, ANNA KELLY PHOTOGRAPHY 225.75, TIM KAISER STUDIOS INC 225.00, 120.00, 90.00 and 90.00, CROWN AWARDS INC 163.51, SP TROPHYDEPOT 145.65, AWARD EMBLEM 26.45, HONORS GRADUATION 279.00, IN POWER MUSIC INC. 575.00, JSD PRODUCTIONS 598.05, IN LABELSTOP INC 260.00 and IN MONOGRAM THAT charges of 136.00 three times, 102.00 twice, 68.00 and 34.00.",
    "",
    "**Credits, adjustments and a fraud dispute**",
    "A line dated 04/24/26 labeled FRAUD DISPUTE posts 1,224.00 to 7000532997000005000. Parenthesized credits throughout the register include GRADUATE EAST LANSING (438.64), GRAND TRAVERSE RESORT (438.97) and (179.52), FSP MISSION POINT (361.81) and (40.00), MICHIGAN WORKS| ASSOCI (350.00), PAY ZEHNDER S BANQUETS (320.00), DISCOUNTSCH (265.16), PAYPAL MIHOSA (257.50), AMAZON MKTPLACE PMTS (134.99), (102.39), (64.34), (53.56) twice, (45.25), (23.75), (19.19), (15.50) and (10.43), JIMMY JOHNS 9031 (125.02), AMAZON MARK BJ8XN6JD1 (107.70), SPIRIT AI (100.09), AMAZON RETA BJ6H58LC1 (86.96), WOODCRAFT 321 (59.96), MAXI AUTO 545 TROY (55.19) twice and (32.89), AMAZON MARK BS4XN54F1 (48.57), AMAZON MARK 744KI8NF3 (47.99), OAKLAND SC (45.00), AMAZON MARK GW82D86G3 (18.79) and (7.79), AMAZON MKTPLACE PMTS (16.16), GFS STORE #1907 (13.98), SUPER DUPER PUBLICATIO (12.73), THE HOME DEPOT #2727 (8.98), BENITO S PIZZA OF TROY (5.73), TST CRISPELLIS - TROY (3.99), KROGER #463 (26.95), HF MUSEUM CALL CENTER (72.00) and PANERA BREAD #600749 (21.49).",
    "",
    "**Total**",
    "The report's final printed figure is 374,998.51.",
]
verbose = "\n".join(verbose_lines)

out = {
    "2026_003_11_may_2026_p_card_report": {
        "paragraph": paragraph,
        "page": page,
        "verbose": verbose,
    }
}

path = "/private/tmp/claude-503/-Users-Alex/baa35be5-50d8-4591-9f9d-77e4125f77ea/scratchpad/wave2_out/w2_001.json"
with open(path, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

for k, v in out.items():
    for t in ("paragraph", "page", "verbose"):
        print(k, t, len(v[t].split()))
print("wrote", path, os.path.getsize(path))
