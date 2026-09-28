"use client";

import { useEffect, useMemo, useRef } from "react";
import type { EChartsOption } from "echarts";

import type { VisualizationResult } from "@/lib/explore-api";

function numberLabel(value: unknown): string {
  if (typeof value !== "number") return String(value ?? "");
  if (!Number.isFinite(value)) return "";
  const absolute = Math.abs(value);
  if ((absolute > 0 && absolute < 0.001) || absolute >= 1_000_000) {
    return value.toExponential(2);
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
}

function optionFor(result: VisualizationResult): EChartsOption {
  const base: EChartsOption = {
    animationDuration: 260,
    textStyle: {
      fontFamily: "var(--font-geist-sans), system-ui, sans-serif",
    },
    title: {
      text: result.title,
      left: 18,
      top: 14,
      textStyle: { fontSize: 15, fontWeight: 600 },
    },
    tooltip: { trigger: "item", confine: true },
    grid: {
      left: 58,
      right: 24,
      top: 58,
      bottom: 54,
      containLabel: true,
    },
  };

  if (result.chart_type === "histogram") {
    const data = result.data.map((item) => {
      const start = Number(item.start);
      const end = Number(item.end);
      return {
        label:
          start === end
            ? numberLabel(start)
            : `${numberLabel(start)}–${numberLabel(end)}`,
        count: Number(item.count),
      };
    });
    return {
      ...base,
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "category",
        name: result.x_label ?? undefined,
        data: data.map((item) => item.label),
        axisLabel: { hideOverlap: true },
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        minInterval: 1,
      },
      series: [
        {
          type: "bar",
          data: data.map((item) => item.count),
          barCategoryGap: "4%",
        },
      ],
    };
  }

  if (result.chart_type === "bar") {
    return {
      ...base,
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      xAxis: {
        type: "category",
        name: result.x_label ?? undefined,
        data: result.data.map((item) => String(item.category ?? "")),
        axisLabel: {
          rotate: result.data.length > 10 ? 34 : 0,
          hideOverlap: true,
        },
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        minInterval: 1,
      },
      series: [
        {
          type: "bar",
          data: result.data.map((item) => Number(item.value)),
        },
      ],
    };
  }

  if (result.chart_type === "line") {
    return {
      ...base,
      tooltip: { trigger: "axis" },
      xAxis: {
        type: "category",
        name: result.x_label ?? undefined,
        data: result.data.map((item) => String(item.x ?? "")),
        axisLabel: { hideOverlap: true },
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        scale: true,
      },
      series: [
        {
          type: "line",
          data: result.data.map((item) => Number(item.y)),
          showSymbol: result.data.length < 120,
          smooth: false,
        },
      ],
      dataZoom:
        result.data.length > 80
          ? [
              { type: "inside" },
              { type: "slider", height: 18, bottom: 8 },
            ]
          : undefined,
    };
  }

  if (result.chart_type === "scatter" || result.chart_type === "qq") {
    const points: Array<[number, number]> = result.data.map((item) => [
      Number(item.x),
      Number(item.y),
    ]);
    const series: NonNullable<EChartsOption["series"]> = [
      {
        type: "scatter",
        data: points,
        symbolSize: points.length > 1500 ? 4 : 7,
        large: points.length > 2000,
      },
    ];
    if (result.chart_type === "qq" && points.length > 1) {
      const slope = Number(result.metadata.slope);
      const intercept = Number(result.metadata.intercept);
      const xs = points.map((point) => point[0]).filter(Number.isFinite);
      const minimum = Math.min(...xs);
      const maximum = Math.max(...xs);
      series.push({
        type: "line",
        data: [
          [minimum, slope * minimum + intercept],
          [maximum, slope * maximum + intercept],
        ],
        showSymbol: false,
        silent: true,
        lineStyle: { type: "dashed", width: 1.5 },
      });
    }
    return {
      ...base,
      xAxis: {
        type: "value",
        name: result.x_label ?? undefined,
        scale: true,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        scale: true,
      },
      series,
    };
  }

  if (result.chart_type === "box") {
    return {
      ...base,
      tooltip: { trigger: "item" },
      xAxis: {
        type: "category",
        data: result.data.map((item) => String(item.category ?? "")),
        name: result.x_label ?? undefined,
        boundaryGap: true,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        scale: true,
      },
      series: [
        {
          type: "boxplot",
          data: result.data.map((item) => item.values as number[]),
        },
      ],
    };
  }

  const categories = Array.from(
    new Set(result.data.map((item) => String(item.x ?? ""))),
  );
  const rows = Array.from(
    new Set(result.data.map((item) => String(item.y ?? ""))),
  );
  const heatmap: Array<[number, number, number]> = result.data.flatMap(
    (item) => {
      if (typeof item.value !== "number" || !Number.isFinite(item.value)) {
        return [];
      }
      return [
        [
          categories.indexOf(String(item.x ?? "")),
          rows.indexOf(String(item.y ?? "")),
          item.value,
        ],
      ];
    },
  );
  return {
    ...base,
    grid: {
      left: 90,
      right: 64,
      top: 58,
      bottom: 72,
      containLabel: true,
    },
    tooltip: { position: "top" },
    xAxis: {
      type: "category",
      data: categories,
      splitArea: { show: true },
      axisLabel: { rotate: categories.length > 6 ? 35 : 0 },
    },
    yAxis: {
      type: "category",
      data: rows,
      splitArea: { show: true },
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 10,
    },
    series: [
      {
        type: "heatmap",
        data: heatmap,
        label: {
          show: categories.length <= 8,
          formatter: (params) =>
            numberLabel(Array.isArray(params.value) ? params.value[2] : ""),
        },
      },
    ],
  };
}

export function ExploreChart({ result }: { result: VisualizationResult }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const option = useMemo(() => optionFor(result), [result]);

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let chart: {
      setOption: (value: EChartsOption, replace?: boolean) => void;
      resize: () => void;
      dispose: () => void;
    } | null = null;

    void import("echarts").then((echarts) => {
      if (disposed || !hostRef.current) return;
      chart = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
      chart.setOption(option, true);
      resizeObserver = new ResizeObserver(() => chart?.resize());
      resizeObserver.observe(hostRef.current);
    });

    return () => {
      disposed = true;
      resizeObserver?.disconnect();
      chart?.dispose();
    };
  }, [option]);

  return (
    <div
      ref={hostRef}
      style={{ width: "100%", height: 470 }}
      role="img"
      aria-label={result.title}
    />
  );
}
