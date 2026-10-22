#
# THOR Auction Score — 0-100, NUMERIC
#
# Column settings:  Aggregation = 5 min   |   Extended Hours = OFF
#
# Direction-neutral conviction. Four 25-point components:
#
#   VOL    relative volume pace, 1.00x -> 2.50x   maps 0 -> 25
#   VWAP   absolute distance from session VWAP, 0 -> 1.00%   maps 0 -> 25
#   MOM    absolute 30-minute rate of change,  0 -> 1.50%    maps 0 -> 25
#   ALIGN  25 when VWAP side, momentum sign and range position agree
#
# Why direction-neutral: the score has to stay a plain number so the
# column sorts numerically. Grade and LONG/SHORT live in their own
# columns. A combined "A+ LONG" text cell sorts alphabetically, which
# puts A- above A and buries the strongest names mid-list.
#
# STATUS: not compiled against thinkorswim. See README verification steps.

def barsPerDay = 78;
def momBars    = 6;
def newSession = GetDay() != GetDay()[1];

# --- session accumulators ---
def cumVol = CompoundValue(1, if newSession then volume else cumVol[1] + volume, volume);
def tpv    = (high + low + close) / 3 * volume;
def cumPV  = CompoundValue(1, if newSession then tpv else cumPV[1] + tpv, tpv);
def sessVwap = if cumVol > 0 then cumPV / cumVol else Double.NaN;

def sessHigh = CompoundValue(1, if newSession then high else Max(sessHigh[1], high), high);
def sessLow  = CompoundValue(1, if newSession then low  else Min(sessLow[1],  low),  low);

# --- relative volume vs same time of day, 5 sessions ---
def refVol = (cumVol[barsPerDay]     + cumVol[barsPerDay * 2]
            + cumVol[barsPerDay * 3] + cumVol[barsPerDay * 4]
            + cumVol[barsPerDay * 5]) / 5;
def relVol = if refVol > 0 then cumVol / refVol else Double.NaN;

# --- components ---
def volPts = Min(25, Max(0, (relVol - 1.0) / 1.5 * 25));

def vwapPct = if sessVwap > 0 then (close - sessVwap) / sessVwap * 100 else Double.NaN;
def vwapPts = Min(25, AbsValue(vwapPct) / 1.00 * 25);

def momPct = if close[momBars] > 0 then (close - close[momBars]) / close[momBars] * 100 else Double.NaN;
def momPts = Min(25, AbsValue(momPct) / 1.50 * 25);

def rangePos  = if sessHigh > sessLow then (close - sessLow) / (sessHigh - sessLow) else 0.5;
def bullAgree = vwapPct > 0 and momPct > 0 and rangePos >= 0.6;
def bearAgree = vwapPct < 0 and momPct < 0 and rangePos <= 0.4;
def alignPts  = if bullAgree or bearAgree then 25 else 0;

plot Score = Round(volPts + vwapPts + momPts + alignPts, 0);

Score.AssignValueColor(
    if Score >= 85 then Color.CYAN
    else if Score >= 75 then Color.GREEN
    else if Score >= 65 then Color.YELLOW
    else Color.GRAY);
