using System.Text.Json.Nodes;
using static SimlibsStudio.Bridge.JsonExt;

namespace SimlibsStudio.Bridge;

public sealed class BridgeException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}

/// <summary>JobEvent.to_dict()（backend_api）。</summary>
public sealed class JobEventDto
{
    public int Seq;
    public string Ts = "";
    public string JobId = "";
    public string Type = "";        // status | log | progress
    public string Message = "";
    public string Level = "info";   // info | ok | warn | error
    public string? Status;
    public double? Progress;
    public bool Final;

    public static JobEventDto Parse(JsonObject o) => new()
    {
        Seq = o.Int("seq"),
        Ts = o.JStr("ts"),
        JobId = o.JStr("job_id"),
        Type = o.JStr("type"),
        Message = o.JStr("message"),
        Level = o.JStr("level", "info"),
        Status = o.Str("status"),
        Progress = o["progress"] is JsonNode pn && pn is not JsonObject and not JsonArray
            ? pn.ToString() is { } s && double.TryParse(s, out var d) ? d : null : null,
        Final = o.Bool("final"),
    };
}

/// <summary>任务视图（list_jobs / get_job）。</summary>
public sealed class JobView
{
    public string JobId = "";
    public string Kind = "";
    public string Status = "";
    public string Summary = "";
    public double Progress;
    public string Duration = "";
    public string? Error;
    public string Created = "";
    public bool Resumable;
    public int CompletedSamples;
    public int TotalSamples;
    public List<JobEventDto> Events = new();

    public static JobView Parse(JsonObject o) => new()
    {
        JobId = o.JStr("job_id"),
        Kind = o.JStr("kind"),
        Status = o.JStr("status"),
        Summary = o.JStr("summary"),
        Progress = o.Dbl("progress"),
        Duration = o.JStr("duration"),
        Error = o.Str("error"),
        Created = o.JStr("created"),
        Resumable = o.Bool("resumable"),
        CompletedSamples = o.Int("completed_samples"),
        TotalSamples = o.Int("total_samples"),
        Events = o.ObjectList("events").Select(JobEventDto.Parse).ToList(),
    };

    public bool IsTerminal => Status is "completed" or "failed" or "cancelled";
}

public sealed class SeriesData
{
    public string Label = "";
    public double[] Xs = Array.Empty<double>();
    public double[] Ys = Array.Empty<double>();
}

/// <summary>单次结果：主谱 xs/ys + 元素离子序列 + meta。</summary>
public sealed class SingleResult
{
    public double[] Xs = Array.Empty<double>();
    public double[] Ys = Array.Empty<double>();
    public JsonObject Meta = new();
    public List<SeriesData> Ions = new();
    public double? FrameValue;
    public int? Frame;

    public static SingleResult Parse(JsonObject o)
    {
        var r = new SingleResult
        {
            Xs = o.DoubleArray("xs"),
            Ys = o.DoubleArray("ys"),
            Meta = o.Obj("meta") ?? new JsonObject(),
            FrameValue = o["value"] is JsonNode vn && vn is JsonValue && double.TryParse(vn.ToString(), out var v) ? v : null,
            Frame = o["frame"] is JsonNode fn && fn is JsonValue && int.TryParse(fn.ToString(), out var f) ? f : null,
        };
        if (o.Obj("series") is { } series && series.Arr("ions") is { } ions)
        {
            foreach (var ion in ions.OfType<JsonObject>())
            {
                r.Ions.Add(new SeriesData
                {
                    Label = ion.JStr("label"),
                    Xs = ion.DoubleArray("xs"),
                    Ys = ion.DoubleArray("ys"),
                });
            }
        }
        return r;
    }
}

public sealed class ScanFrameInfo
{
    public double Value;
    public bool Loaded;
    public string? ActualResolution;
    public string? IntensityScale;
    public double[] Xs = Array.Empty<double>();
    public double[] Ys = Array.Empty<double>();

    public static ScanFrameInfo Parse(JsonObject o) => new()
    {
        Value = o.Dbl("value"),
        Loaded = o.Bool("loaded"),
        ActualResolution = o.Str("actual_resolution"),
        IntensityScale = o.Str("intensity_scale"),
        Xs = o.DoubleArray("xs"),
        Ys = o.DoubleArray("ys"),
    };
}

/// <summary>扫描结果；真实后端为懒帧（frames 只有元信息），mock 为整包（帧内嵌 xs/ys）。</summary>
public sealed class ScanResult
{
    public string Axis = "";
    public string Unit = "";
    public string ParamsSummary = "";
    public string JobId = "";
    public List<ScanFrameInfo> Frames = new();
    public bool Embedded;

    public static ScanResult Parse(JsonObject o)
    {
        var r = new ScanResult
        {
            Axis = o.JStr("axis"),
            Unit = o.JStr("unit"),
            ParamsSummary = o.JStr("params_summary"),
            JobId = o.JStr("job_id"),
        };
        foreach (var f in o.ObjectList("frames"))
        {
            r.Frames.Add(ScanFrameInfo.Parse(f));
        }
        r.Embedded = r.Frames.Count > 0 && r.Frames[0].Xs.Length > 0;
        return r;
    }
}

public sealed class BatchSampleRow
{
    public string Name = "";
    public double Te;
    public double Ne;
    public string Composition = "";
}

/// <summary>批量结果。</summary>
public sealed class BatchResult
{
    public int Total;
    public int Completed;
    public int Failed;
    public bool Partial;
    public string IntensityScale = "";
    public List<BatchSampleRow> Samples = new();
    public bool TrainingAvailable;
    public string TrainingReason = "";
    public bool ParamsAvailable;
    public bool TemplateAvailable;
    public List<string> WideCols = new();
    public List<List<string>> WideRows = new();
    public string WideNote = "";

    public static BatchResult Parse(JsonObject o)
    {
        var r = new BatchResult
        {
            IntensityScale = o.JStr("intensity_scale"),
            ParamsAvailable = o.Bool("actual_parameters_available"),
            TemplateAvailable = o.Bool("template_csv_available"),
        };
        if (o.Obj("summary") is { } s)
        {
            r.Total = s.Int("total");
            r.Completed = s.Int("completed");
            r.Failed = s.Int("failed");
            r.Partial = s.Bool("partial");
        }
        foreach (var sm in o.ObjectList("samples"))
        {
            r.Samples.Add(new BatchSampleRow
            {
                Name = sm.JStr("name"),
                Te = sm.Dbl("te"),
                Ne = sm.Dbl("ne"),
                Composition = string.Join(" · ", sm.ObjectList("composition")
                    .Select(c => $"{c.JStr("el")} {c.Dbl("pct"):0.##}%")),
            });
        }
        var tp = o.Obj("training_package");
        r.TrainingAvailable = tp?.Bool("available") == true;
        r.TrainingReason = tp?.JStr("reason") ?? "";
        if (o.Obj("wide") is { } wide)
        {
            r.WideNote = wide.JStr("note");
            if (wide.Arr("cols") is { } cols)
                foreach (var c in cols) r.WideCols.Add(c?.ToString() ?? "");
            if (wide.Arr("rows") is { } rows)
            {
                foreach (var row in rows.OfType<JsonArray>())
                {
                    r.WideRows.Add(row.Select(c => c?.ToString() ?? "").ToList());
                }
            }
        }
        return r;
    }
}

/// <summary>export 命令的返回（bytes 走 b64，文本走 text）。</summary>
public sealed class ExportResult
{
    public byte[]? Bytes;
    public string? Text;
    public string MediaType = "";
    public string Filename = "";

    public static ExportResult Parse(JsonObject o) => new()
    {
        Bytes = o.Str("b64") is { } b64 && b64.Length > 0 ? Convert.FromBase64String(b64) : null,
        Text = o.Str("text"),
        MediaType = o.JStr("media_type"),
        Filename = o.JStr("filename"),
    };
}

/// <summary>历史 CSV 离线打开结果（history.load_history）。</summary>
public sealed class HistoryResult
{
    public List<SeriesData> Series = new();
    public JsonObject Meta = new();
}
