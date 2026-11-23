// Research harness: one fixed ORT shared library and one persistent model session.
// Inputs and outputs are private temporary tensor files. Export text summaries only.
#include "onnxruntime_c_api.h"
#include <dlfcn.h>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace fs = std::filesystem;
static const OrtApi* api;

static void check(OrtStatus* s) {
  if (!s) return;
  std::string message = api->GetErrorMessage(s);
  api->ReleaseStatus(s);
  throw std::runtime_error(message);
}

static std::vector<std::string> split(const std::string& text, char sep) {
  std::vector<std::string> parts;
  std::istringstream stream(text);
  std::string part;
  while (std::getline(stream, part, sep)) parts.push_back(part);
  return parts;
}

static ONNXTensorElementDataType type_of(const std::string& name) {
  if (name == "float32") return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
  if (name == "int64") return ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64;
  throw std::runtime_error("unsupported tensor type: " + name);
}

static size_t item_size(ONNXTensorElementDataType type) {
  if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) return 4;
  if (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64) return 8;
  throw std::runtime_error("unexpected output tensor type: " + std::to_string(type));
}

static std::string shape_text(const std::vector<int64_t>& shape) {
  if (shape.empty()) return "scalar";
  std::ostringstream text;
  for (size_t i = 0; i < shape.size(); ++i) {
    if (i) text << ',';
    text << shape[i];
  }
  return text.str();
}

struct Values {
  std::vector<OrtValue*> items;
  ~Values() { for (auto* item : items) if (item) api->ReleaseValue(item); }
};

struct Context {
  OrtEnv* env = nullptr;
  OrtSessionOptions* options = nullptr;
  OrtSession* session = nullptr;
  OrtMemoryInfo* memory = nullptr;
  OrtAllocator* allocator = nullptr;
  std::vector<char*> outputs;
  ~Context() {
    for (auto* name : outputs) allocator->Free(allocator, name);
    if (session) api->ReleaseSession(session);
    if (memory) api->ReleaseMemoryInfo(memory);
    if (options) api->ReleaseSessionOptions(options);
    if (env) api->ReleaseEnv(env);
  }
};

static void run(Context& ctx, const fs::path& input_manifest, const fs::path& output_dir) {
  std::ifstream list(input_manifest);
  if (!list) throw std::runtime_error("cannot read input manifest");
  std::vector<std::string> names;
  std::vector<std::vector<char>> data;
  std::vector<std::vector<int64_t>> shapes;
  std::vector<ONNXTensorElementDataType> types;
  std::string line;
  while (std::getline(list, line)) {
    auto fields = split(line, '\t');
    if (fields.size() != 4) throw std::runtime_error("input row requires name/type/shape/path");
    names.push_back(fields[0]);
    types.push_back(type_of(fields[1]));
    std::vector<int64_t> shape;
    if (fields[2] != "scalar") {
      for (const auto& dim : split(fields[2], ',')) shape.push_back(std::stoll(dim));
    }
    size_t count = 1;
    for (auto dim : shape) {
      if (dim < 0) throw std::runtime_error("input shape must be concrete");
      count *= static_cast<size_t>(dim);
    }
    shapes.push_back(std::move(shape));
    std::ifstream input(fields[3], std::ios::binary);
    if (!input) throw std::runtime_error("cannot read input tensor");
    data.emplace_back(std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>());
    if (data.back().size() != count * item_size(types.back()))
      throw std::runtime_error("input shape/type/byte count differ");
  }
  std::vector<const char*> input_names;
  std::vector<const OrtValue*> input_values;
  Values inputs;
  for (size_t i = 0; i < names.size(); ++i) {
    OrtValue* tensor = nullptr;
    check(api->CreateTensorWithDataAsOrtValue(ctx.memory, data[i].data(), data[i].size(),
      shapes[i].data(), shapes[i].size(), types[i], &tensor));
    inputs.items.push_back(tensor);
    input_names.push_back(names[i].c_str());
    input_values.push_back(tensor);
  }
  Values results;
  results.items.resize(ctx.outputs.size(), nullptr);
  std::vector<const char*> output_names(ctx.outputs.begin(), ctx.outputs.end());
  check(api->Run(ctx.session, nullptr, input_names.data(), input_values.data(), input_values.size(),
    output_names.data(), output_names.size(), results.items.data()));
  fs::create_directories(output_dir);
  std::ofstream manifest(output_dir / "outputs.tsv");
  if (!manifest) throw std::runtime_error("cannot write output manifest");
  for (size_t i = 0; i < results.items.size(); ++i) {
    OrtTensorTypeAndShapeInfo* info_raw = nullptr;
    check(api->GetTensorTypeAndShape(results.items[i], &info_raw));
    auto release_info = [](OrtTensorTypeAndShapeInfo* info) { api->ReleaseTensorTypeAndShapeInfo(info); };
    std::unique_ptr<OrtTensorTypeAndShapeInfo, decltype(release_info)> info(info_raw, release_info);
    ONNXTensorElementDataType type;
    size_t rank, count;
    check(api->GetTensorElementType(info.get(), &type));
    check(api->GetDimensionsCount(info.get(), &rank));
    std::vector<int64_t> shape(rank);
    check(api->GetDimensions(info.get(), shape.data(), rank));
    check(api->GetTensorShapeElementCount(info.get(), &count));
    void* bytes = nullptr;
    check(api->GetTensorMutableData(results.items[i], &bytes));
    const auto output = output_dir / ("out-" + std::to_string(i) + ".bin");
    std::ofstream file(output, std::ios::binary);
    file.write(static_cast<const char*>(bytes), count * item_size(type));
    file.close();
    if (!file) throw std::runtime_error("cannot write output tensor");
    manifest << ctx.outputs[i] << '\t'
      << (type == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT ? "float32" : "int64") << '\t'
      << shape_text(shape) << '\t' << output.string() << '\n';
  }
  manifest.close();
  if (!manifest) throw std::runtime_error("cannot finish output manifest");
}

int main(int argc, char** argv) {
  try {
    if (argc != 4) throw std::runtime_error("usage: ort_runner LIBRARY MODEL THREADS");
    const int threads = std::stoi(argv[3]);
    void* library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
    if (!library) throw std::runtime_error(dlerror());
    auto get_base = reinterpret_cast<const OrtApiBase* (*)()>(dlsym(library, "OrtGetApiBase"));
    if (!get_base) throw std::runtime_error("OrtGetApiBase missing");
    const auto* base = get_base();
    api = base->GetApi(ORT_API_VERSION);
    if (!api) throw std::runtime_error("ORT API version unavailable");
    {
      Context ctx;
      check(api->CreateEnv(ORT_LOGGING_LEVEL_WARNING, "six-model-research", &ctx.env));
      check(api->CreateSessionOptions(&ctx.options));
      check(api->SetIntraOpNumThreads(ctx.options, threads));
      check(api->SetInterOpNumThreads(ctx.options, threads));
      check(api->SetSessionExecutionMode(ctx.options, ORT_SEQUENTIAL));
      check(api->SetSessionGraphOptimizationLevel(ctx.options, ORT_ENABLE_ALL));
      check(api->CreateSession(ctx.env, argv[2], ctx.options, &ctx.session));
      check(api->CreateCpuMemoryInfo(OrtArenaAllocator, OrtMemTypeDefault, &ctx.memory));
      check(api->GetAllocatorWithDefaultOptions(&ctx.allocator));
      size_t count;
      check(api->SessionGetOutputCount(ctx.session, &count));
      for (size_t i = 0; i < count; ++i) {
        char* name = nullptr;
        check(api->SessionGetOutputName(ctx.session, i, ctx.allocator, &name));
        ctx.outputs.push_back(name);
      }
      std::cout << "ready\t" << base->GetVersionString() << '\t' << count << std::endl;
      std::string command;
      while (std::getline(std::cin, command) && command != "quit") {
        auto fields = split(command, '\t');
        if (fields.size() != 2) throw std::runtime_error("run requires manifest/output directory");
        run(ctx, fields[0], fields[1]);
        std::cout << "ok\t" << (fs::path(fields[1]) / "outputs.tsv").string() << std::endl;
      }
    }
    dlclose(library);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "runner error: " << error.what() << '\n';
    return 1;
  }
}
