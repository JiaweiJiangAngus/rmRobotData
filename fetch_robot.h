#include <iostream>
#include <fstream>
#include <string>
#include <curl/curl.h>
#include <nlohmann/json.hpp>
#include <map>
#include <filesystem>

using json = nlohmann::json;
namespace fs = std::filesystem;


// libcurl 回调，把下载数据写入 string
size_t WriteCallback(void* contents, size_t size, size_t nmemb, void* userp) {
    ((std::string*)userp)->append((char*)contents, size * nmemb);
    return size * nmemb;
}

// 安全把 json 字段转成 string
std::string get_string(const json& j, const std::string& key) {
    if (!j.contains(key) || j[key].is_null()) return "";
    if (j[key].is_string()) return j[key].get<std::string>();
    if (j[key].is_number_integer()) return std::to_string(j[key].get<int>());
    if (j[key].is_number_float()) return std::to_string(j[key].get<double>());
    return j[key].dump();
}

// 检查 zoneName 是否包含目标关键词
bool is_target_zone(const std::string& zoneName) {
    return zoneName.find("联盟赛") != std::string::npos ||
           zoneName.find("部赛区") != std::string::npos ||
           zoneName.find("复活赛") != std::string::npos ||
           zoneName.find("全国赛") != std::string::npos;
}

inline int robot_ID(std::string type_name) {
    if (type_name == "Infantry") return 0;
    if (type_name == "Hero") return 1;
    if (type_name == "Sapper") return 2;
    if (type_name == "Airplane") return 3;
    if (type_name == "Guard") return 4;
    if (type_name == "Dart") return 5;
    if (type_name == "Radar") return 6;
    return 0;
}