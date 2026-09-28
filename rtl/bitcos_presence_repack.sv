// Architecture B presence loader: repacks a byte-packed presence bitmap into
// 40-bit rows of eight 5-bit presence words for a 5-bit-word presence bank.
//
// Five consecutive input bytes form one 40-bit row, least significant bit
// first, so row bit 5*j+l is the presence bit of lane l in group j of the
// row. The first four bytes are held in a 32-bit register; the fifth goes
// straight to the output together with them, with row_valid for one cycle.
// start (with or without byte_valid) restarts row assembly at byte 0, so each
// weight matrix begins on a row boundary.
// These are physical 40-bit loader rows, not logical matrix rows. Before
// byte packing, zero-pad each logical matrix row's presence bits to a multiple
// of five. The loader preserves that alignment; it does not insert padding.
// Supply zero bytes to complete the final five-byte block when necessary.
module bitcos_presence_repack (
    input  logic        clk,
    input  logic        rst_n,
    input  logic        start,
    input  logic        byte_valid,
    input  logic [7:0]  presence_byte,
    output logic        row_valid,
    output logic [39:0] row
);
    logic [2:0] count;
    logic [31:0] held;

    assign row_valid = byte_valid && (start ? 1'b0 : count == 3'd4);
    assign row = {presence_byte, held};

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n)
            count <= '0;
        else if (start)
            count <= {2'b00, byte_valid};
        else if (byte_valid)
            count <= (count == 3'd4) ? 3'd0 : count + 3'd1;
    end

    always_ff @(posedge clk) begin
        if (byte_valid) begin
            if (start || count == 3'd0) held[7:0] <= presence_byte;
            if (!start && count == 3'd1) held[15:8] <= presence_byte;
            if (!start && count == 3'd2) held[23:16] <= presence_byte;
            if (!start && count == 3'd3) held[31:24] <= presence_byte;
        end
    end
endmodule
