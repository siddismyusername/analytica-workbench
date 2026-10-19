"use client";

import { useEffect, useRef } from "react";
import type { EChartsOption } from "echarts";

import type { VisualizationResult } from "@/lib/explore-api";

type ChartTheme = {
  accent: string;
  border: string;
  content: string;
  fontFamily: string;
  muted: string;
  surfaceStrong: string;
  text: string;
  reducedMotion: boolean;
};

function numberLabel(value: unknown): string {
  if (typeof value !== "number") return String(value ?? "");
  if (!Number.isFinite(value)) return "";
  const absolute = Math.abs(value);
  if ((absolute > 0 && absolute < 0.001) || absolute >= 1_000_000) {
    return value.toExponential(2);
  }
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 3 }).format(value);
}

function readChartTheme(host: HTMLElement): ChartTheme {
  const root = getComputedStyle(document.documentElement);
  const hostStyle = getComputedStyle(host);
  const token = (name: string, fallback: string) => root.getPropertyValue(name).trim() || fallback;

  return {
    accent: token("--accent", "#2563eb"),
    border: token("--border", "rgba(15, 23, 42, 0.09)"),
    content: token("--content", "#ffffff"),
    fontFamily: hostStyle.fontFamily || "ui-sans-serif, system-ui, sans-serif",
    muted: token("--muted", "#6b717b"),
    surfaceStrong: token("--surface-strong", "rgba(255, 255, 255, 0.94)"),
    text: token("--text", "#15171a"),
    reducedMotion: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  };
}

function optionFor(result: VisualizationResult, theme: ChartTheme): EChartsOption {
  const axisLine = { lineStyle: { color: theme.border } };
  const splitLine = { lineStyle: { color: theme.border } };
  const axisLabel = { color: theme.muted };

  const base: EChartsOption = {
    animationDuration: theme.reducedMotion ? 0 : 260,
    color: [theme.accent],
    backgroundColor: "transparent",
    textStyle: {
      fontFamily: theme.fontFamily,
      color: theme.text,
    },
    title: {
      text: result.title,
      left: 18,
      top: 14,
      textStyle: { fontSize: 15, fontWeight: 600, color: theme.text },
    },
    tooltip: {
      trigger: "item",
      confine: true,
      backgroundColor: theme.surfaceStrong,
      borderColor: theme.border,
      textStyle: { color: theme.text },
    },
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
        label: start === end ? numberLabel(start) : `${numberLabel(start)}–${numberLabel(end)}`,
        count: Number(item.count),
      };
    });
    return {
      ...base,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: theme.surfaceStrong,
        borderColor: theme.border,
        textStyle: { color: theme.text },
      },
      xAxis: {
        type: "category",
        name: result.x_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        data: data.map((item) => item.label),
        axisLabel: { ...axisLabel, hideOverlap: true },
        axisLine,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        minInterval: 1,
        axisLabel,
        axisLine,
        splitLine,
      },
      series: [{ type: "bar", data: data.map((item) => item.count), barCategoryGap: "4%" }],
    };
  }

  if (result.chart_type === "bar") {
    return {
      ...base,
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "shadow" },
        backgroundColor: theme.surfaceStrong,
        borderColor: theme.border,
        textStyle: { color: theme.text },
      },
      xAxis: {
        type: "category",
        name: result.x_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        data: result.data.map((item) => String(item.category ?? "")),
        axisLabel: { color: theme.muted, rotate: result.data.length > 10 ? 34 : 0, hideOverlap: true },
        axisLine,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        minInterval: 1,
        axisLabel,
        axisLine,
        splitLine,
      },
      series: [{ type: "bar", data: result.data.map((item) => Number(item.value)) }],
    };
  }

  if (result.chart_type === "line") {
    return {
      ...base,
      tooltip: {
        trigger: "axis",
        backgroundColor: theme.surfaceStrong,
        borderColor: theme.border,
        textStyle: { color: theme.text },
      },
      xAxis: {
        type: "category",
        name: result.x_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        data: result.data.map((item) => String(item.x ?? "")),
        axisLabel: { ...axisLabel, hideOverlap: true },
        axisLine,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        scale: true,
        axisLabel,
        axisLine,
        splitLine,
      },
      series: [{ type: "line", data: result.data.map((item) => Number(item.y)), showSymbol: result.data.length < 120, smooth: false }],
      dataZoom: result.data.length > 80 ? [{ type: "inside" }, { type: "slider", height: 18, bottom: 8 }] : undefined,
    };
  }

  if (result.chart_type === "scatter" || result.chart_type === "qq") {
    const points: Array<[number, number]> = result.data.map((item) => [Number(item.x), Number(item.y)]);
    const series: NonNullable<EChartsOption["series"]> = [{
      type: "scatter",
      data: points,
      symbolSize: points.length > 1500 ? 4 : 7,
      large: points.length > 2000,
    }];

    if (result.chart_type === "qq" && points.length > 1) {
      const slope = Number(result.metadata.slope);
      const intercept = Number(result.metadata.intercept);
      const xs = points.map((point) => point[0]).filter(Number.isFinite);
      const minimum = Math.min(...xs);
      const maximum = Math.max(...xs);
      series.push({
        type: "line",
        data: [[minimum, slope * minimum + intercept], [maximum, slope * maximum + intercept]],
        showSymbol: false,
        silent: true,
        lineStyle: { type: "dashed", width: 1.5, color: theme.muted },
      });
    }

    return {
      ...base,
      xAxis: {
        type: "value",
        name: result.x_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        scale: true,
        axisLabel,
        axisLine,
        splitLine,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        scale: true,
        axisLabel,
        axisLine,
        splitLine,
      },
      series,
    };
  }

  if (result.chart_type === "box") {
    return {
      ...base,
      tooltip: {
        trigger: "item",
        backgroundColor: theme.surfaceStrong,
        borderColor: theme.border,
        textStyle: { color: theme.text },
      },
      xAxis: {
        type: "category",
        data: result.data.map((item) => String(item.category ?? "")),
        name: result.x_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        boundaryGap: true,
        axisLabel,
        axisLine,
      },
      yAxis: {
        type: "value",
        name: result.y_label ?? undefined,
        nameTextStyle: { color: theme.muted },
        scale: true,
        axisLabel,
        axisLine,
        splitLine,
      },
      series: [{ type: "boxplot", data: result.data.map((item) => item.values as number[]) }],
    };
  }

  const categories = Array.from(new Set(result.data.map((item) => String(item.x ?? ""))));
  const rows = Array.from(new Set(result.data.map((item) => String(item.y ?? ""))));
  const heatmap: Array<[number, number, number]> = result.data.flatMap((item) => {
    if (typeof item.value !== "number" || !Number.isFinite(item.value)) return [];
    return [[categories.indexOf(String(item.x ?? "")), rows.indexOf(String(item.y ?? "")), item.value]];
  });

  return {
    ...base,
    grid: { left: 90, right: 64, top: 58, bottom: 72, containLabel: true },
    tooltip: {
      position: "top",
      backgroundColor: theme.surfaceStrong,
      borderColor: theme.border,
      textStyle: { color: theme.text },
    },
    xAxis: {
      type: "category",
      data: categories,
      splitArea: { show: true },
      axisLabel: { color: theme.muted, rotate: categories.length > 6 ? 35 : 0 },
      axisLine,
    },
    yAxis: {
      type: "category",
      data: rows,
      splitArea: { show: true },
      axisLabel,
      axisLine,
    },
    visualMap: {
      min: -1,
      max: 1,
      calculable: true,
      orient: "horizontal",
      left: "center",
      bottom: 10,
      textStyle: { color: theme.muted },
    },
    series: [{
      type: "heatmap",
      data: heatmap,
      label: {
        show: categories.length <= 8,
        color: theme.text,
        formatter: (params) => numberLabel(Array.isArray(params.value) ? params.value[2] : ""),
      },
    }],
  };
}

export function ExploreChart({ result }: { result: VisualizationResult }) {
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let resizeObserver: ResizeObserver | null = null;
    let chart: {
      setOption: (value: EChartsOption, replace?: boolean) => void;
      resize: () => void;
      dispose: () => void;
    } | null = null;

    const colorScheme = window.matchMedia("(prefers-color-scheme: dark)");
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");

    const applyTheme = () => {
      if (!chart || !hostRef.current) return;
      chart.setOption(optionFor(result, readChartTheme(hostRef.current)), true);
    };

    void import("echarts").then((echarts) => {
      if (disposed || !hostRef.current) return;
      chart = echarts.init(hostRef.current, undefined, { renderer: "canvas" });
      applyTheme();
      resizeObserver = new ResizeObserver(() => chart?.resize());
      resizeObserver.observe(hostRef.current);
      colorScheme.addEventListener("change", applyTheme);
      reducedMotion.addEventListener("change", applyTheme);
    });

    return () => {
      disposed = true;
      colorScheme.removeEventListener("change", applyTheme);
      reducedMotion.removeEventListener("change", applyTheme);
      resizeObserver?.disconnect();
      chart?.dispose();
    };
  }, [result]);

  return (
    <div
      ref={hostRef}
      style={{ width: "100%", height: 470 }}
      role="img"
      aria-label={result.title}
    />
  );
}
