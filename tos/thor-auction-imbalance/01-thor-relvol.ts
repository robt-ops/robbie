#
# THOR RelVol — session-paced relative volume
#
# Column settings:  Aggregation = 5 min   |   Extended Hours = OFF
#
# Compares today's cumulative RTH volume against the average cumulative
# volume at the SAME time of day over the previous 5 sessions. 1.00 means
# today is tracking the recent norm; 2.00 means double the normal pace.
#
# Time-of-day matching matters here: a flat "ADV / minutes elapsed" pace
# model reads ~4-6x at 09:35 on every symbol every day, because opening
# volume is structurally front-loaded. This version has no such bias.
#
# STATUS: not compiled against thinkorswim. See README verification steps.

def barsPerDay = 78;                       # 5-min bars in 09:30-16:00 RTH
def newSession = GetDay() != GetDay()[1];

def cumVol = CompoundValue(1, if newSession then volume else cumVol[1] + volume, volume);

def refVol = (cumVol[barsPerDay]
            + cumVol[barsPerDay * 2]
            + cumVol[barsPerDay * 3]
            + cumVol[barsPerDay * 4]
            + cumVol[barsPerDay * 5]) / 5;

plot RelVol = if refVol > 0 then cumVol / refVol else Double.NaN;

RelVol.AssignValueColor(
    if RelVol >= 2.5 then Color.CYAN
    else if RelVol >= 1.5 then Color.GREEN
    else if RelVol >= 1.0 then Color.YELLOW
    else Color.GRAY);
