using System.Text.Json.Nodes;

namespace SimlibsStudio.Bridge;

/// <summary>System.Text.Json 的轻量取值扩展（容忍缺键/错型）。</summary>
public static class JsonExt
{
    public static string? Str(this JsonObject? obj, string key)
        => obj is not null && obj[key] is JsonNode n && n is not JsonArray and not JsonObject
            ? n.ToString() : null;

    public static double Dbl(this JsonObject? obj, string key, double def = 0)
    {
        if (obj is not null && obj[key] is JsonNode n)
        {
            try
            {
                if (n is JsonValue v && v.TryGetValue<double>(out var d)) return d;
                if (double.TryParse(n.ToString(), out var p)) return p;
            }
            catch { /* fallthrough */ }
        }
        return def;
    }

    public static int Int(this JsonObject? obj, string key, int def = 0)
        => (int)Math.Round(Dbl(obj, key, def));

    public static bool Bool(this JsonObject? obj, string key, bool def = false)
    {
        if (obj is not null && obj[key] is JsonValue v && v.TryGetValue<bool>(out var b)) return b;
        return def;
    }

    public static JsonObject? Obj(this JsonObject? obj, string key)
        => obj is not null && obj[key] is JsonObject o ? o : null;

    public static JsonArray? Arr(this JsonObject? obj, string key)
        => obj is not null && obj[key] is JsonArray a ? a : null;

    public static double[] DoubleArray(this JsonObject? obj, string key)
        => obj is not null && obj[key] is JsonArray a ? ToDoubleArray(a) : Array.Empty<double>();

    public static double[] ToDoubleArray(JsonArray array)
    {
        var result = new double[array.Count];
        for (var i = 0; i < array.Count; i++)
        {
            if (array[i] is JsonValue v)
            {
                if (v.TryGetValue<double>(out var d)) result[i] = d;
                else if (double.TryParse(v.ToString(), out var p)) result[i] = p;
            }
        }
        return result;
    }

    public static List<JsonObject> ObjectList(this JsonObject? obj, string key)
    {
        var list = new List<JsonObject>();
        if (obj is not null && obj[key] is JsonArray a)
        {
            foreach (var item in a)
                if (item is JsonObject o) list.Add(o);
        }
        return list;
    }

    public static string JStr(this JsonObject? obj, string key, string def = "")
        => Str(obj, key) ?? def;
}
